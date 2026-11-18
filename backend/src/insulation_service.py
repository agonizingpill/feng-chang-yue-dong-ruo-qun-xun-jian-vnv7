from datetime import datetime
from sqlalchemy import select
from fastapi import HTTPException
from .models import Hive
from .season_models import InsulationLot,InsulationInstall,InsulationRecall,InsulationRecallItem
from .yard_service import require,audit
from .recall_service import lock_season,open_items,recalled_install_item,stock_for

def active_install(db,hive_id,lock=False):
    q=select(InsulationInstall).where(InsulationInstall.hive_id==hive_id,InsulationInstall.state.in_(['installed','accepted']))
    if lock:q=q.with_for_update()
    return db.scalar(q)

def lot_usable(db,lot_id):
    lot=require(db,InsulationLot,lot_id,True)
    if lot.state!='active':raise HTTPException(409,'保温物料隔离或库存不足')
    if db.scalar(select(InsulationRecall.id).where(InsulationRecall.lot_id==lot.id,InsulationRecall.state=='open')):raise HTTPException(409,'该批次正被召回，不能用于换装')
    return lot

def take_units(db,lot,units):
    if lot.available_units<units:raise HTTPException(409,'保温物料隔离或库存不足')
    lot.available_units-=units

def settle_return(db,row,reusable,u):
    if reusable>row.units:raise HTTPException(409,'归还可复用件数不得超原安装量')
    lot=require(db,InsulationLot,row.lot_id,True)
    if recalled_install_item(db,row.id,True):stock_for(db,lot.id).units+=reusable
    else:lot.available_units+=reusable
    row.returned_units=reusable;row.removed_by=u.email;row.state='removed'

def install(db,b,u):
    lock_season(db)
    h=require(db,Hive,b.hive_id,True)
    if active_install(db,h.id,True):raise HTTPException(409,'该箱已有活跃保温安装')
    pending=open_items(db,h.id,True)
    item=None
    for i in pending:
        if i.state=='recovered':
            rep=db.get(InsulationInstall,i.replacement_install_id) if i.replacement_install_id else None
            if rep is None or rep.state=='removed':
                item=i;break
    if item and item.replacement_install_id:item.replacement_install_id=None
    if pending and not item:raise HTTPException(409,'该箱安装已被主管召回，须先拆除召回安装再换装合格批次')
    lot=lot_usable(db,b.lot_id)
    take_units(db,lot,b.units)
    row=InsulationInstall(**b.model_dump(),installed_by=u.email);db.add(row);db.flush()
    if item:
        item.replacement_install_id=row.id
        audit(db,u,f'召回换装 {h.code} 接着召回项ITEM-{item.id} 办理，安装INS-{row.id}')
    else:audit(db,u,f'安装保温 {h.code} 扣{b.units}件')
    db.commit();return row

def change(db,key,b,u,action):
    lock_season(db)
    ref=require(db,InsulationInstall,key);h=require(db,Hive,ref.hive_id,True)
    row=require(db,InsulationInstall,key,True)
    if action=='ventilation':
        if row.state!='installed':raise HTTPException(409,'验收后通风记录冻结')
        row.ventilation_checked=b.ventilation_checked
    elif action=='accept':
        if row.state!='installed' or not row.ventilation_checked:raise HTTPException(409,'须安装且通风已核查，不能重复验收')
        if db.scalar(select(InsulationRecallItem.id).where(InsulationRecallItem.install_id==row.id)):raise HTTPException(409,'该安装来自被召回批次，不能验收，请拆回并按合格批次换装')
        item=db.scalar(select(InsulationRecallItem).where(InsulationRecallItem.replacement_install_id==row.id).with_for_update())
        if item and item.state!='resolved':
            item.state='resolved';item.resolved_at=datetime.utcnow()
            audit(db,u,f'召回项ITEM-{item.id}换装验收完成，解除{h.code}限制')
        row.state='accepted';row.accepted_by=u.email
    else:
        if row.state not in ['installed','accepted']:raise HTTPException(409,'保温物料已拆除归还，不能重复')
        item=recalled_install_item(db,row.id,True)
        rep_item=db.scalar(select(InsulationRecallItem).where(InsulationRecallItem.replacement_install_id==row.id).with_for_update())
        settle_return(db,row,b.reusable_units,u)
        if item and item.state=='locked':
            item.state='recovered';item.recovered_units+=b.reusable_units
        if rep_item and rep_item.state!='recovered':
            recall=require(db,InsulationRecall,rep_item.recall_id,True)
            if recall.state=='open':
                rep_item.state='recovered';rep_item.replacement_install_id=None
    audit(db,u,f'保温安装{key} {action}');db.commit();return row

def replace(db,b,u):
    lock_season(db)
    h=require(db,Hive,b.hive_id,True)
    pending=open_items(db,h.id,True)
    if not pending:raise HTTPException(409,'该箱没有未销项召回，无需换装')
    item=next((i for i in pending if i.state=='recovered'),pending[0])
    if item.state=='locked':
        row=require(db,InsulationInstall,item.install_id,True)
        if row.state!='removed':
            if b.reusable_units>row.units:raise HTTPException(409,'归还可复用件数不得超原安装量')
            settle_return(db,row,b.reusable_units,u)
            item.recovered_units+=b.reusable_units
        item.state='recovered'
    if item.replacement_install_id:
        existing=db.get(InsulationInstall,item.replacement_install_id)
        if existing and existing.state!='removed':
            if b.units!=existing.units or b.lot_id!=existing.lot_id:raise HTTPException(409,'该召回项已登记换装，请继续使用原换装安装办理')
            return existing
        item.replacement_install_id=None
    if active_install(db,h.id,True):raise HTTPException(409,'该箱已有其他活跃保温安装，不能重复换装')
    lot=lot_usable(db,b.lot_id)
    take_units(db,lot,b.units)
    new=InsulationInstall(hive_id=h.id,lot_id=lot.id,units=b.units,ventilation_checked=b.ventilation_checked,installed_by=u.email)
    db.add(new);db.flush();item.replacement_install_id=new.id
    audit(db,u,f'召回换装 {h.code} 拆回{item.recovered_units}件入隔离库存，安装合格批次{lot.code} {b.units}件 INS-{new.id}')
    db.commit();return new
