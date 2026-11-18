from sqlalchemy import select,text
from fastapi import HTTPException
from .models import Hive
from .season_models import InsulationLot,InsulationInstall,InsulationRecall,InsulationRecallItem,InsulationQuarantineStock,SpringReview,SpringRecallMark
from .yard_service import require,audit
OPEN_ITEM_STATES=('locked','recovered')
SEASON_LOCK=7820461

def lock_season(db):
    if db.get_bind().dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':SEASON_LOCK})

def open_items(db,hive_id,lock=False):
    q=select(InsulationRecallItem).where(InsulationRecallItem.hive_id==hive_id,InsulationRecallItem.state.in_(OPEN_ITEM_STATES)).order_by(InsulationRecallItem.id)
    if lock:q=q.with_for_update()
    return db.scalars(q).all()

def assert_unlocked(db,hive_id,purpose):
    if open_items(db,hive_id,True):raise HTTPException(409,f'该箱安装已被主管召回，完成合格批次换装并重新验收前不能{purpose}')

def recalled_install_item(db,install_id,lock=False):
    q=select(InsulationRecallItem).where(InsulationRecallItem.install_id==install_id,InsulationRecallItem.state.in_(OPEN_ITEM_STATES))
    if lock:q=q.with_for_update()
    return db.scalar(q)

def stock_for(db,lot_id):
    row=db.scalar(select(InsulationQuarantineStock).where(InsulationQuarantineStock.lot_id==lot_id).with_for_update())
    if not row:row=InsulationQuarantineStock(lot_id=lot_id,units=0);db.add(row);db.flush()
    return row

def mark_reviews(db,recall_id,install_ids):
    if not install_ids:return
    rows=db.scalars(select(SpringReview).where(SpringReview.install_id.in_(install_ids),SpringReview.state=='passed')).all()
    for review in rows:
        if not db.scalar(select(SpringRecallMark.id).where(SpringRecallMark.recall_id==recall_id,SpringRecallMark.review_id==review.id)):
            db.add(SpringRecallMark(recall_id=recall_id,review_id=review.id,install_id=review.install_id))

def open_recall(db,b,u):
    lock_season(db)
    lot=require(db,InsulationLot,b.lot_id,True)
    if db.scalar(select(InsulationRecall.id).where(InsulationRecall.lot_id==lot.id,InsulationRecall.state=='open')):raise HTTPException(409,'该批次已有未关闭召回')
    installs=db.scalars(select(InsulationInstall).where(InsulationInstall.lot_id==lot.id,InsulationInstall.state.in_(['installed','accepted'])).order_by(InsulationInstall.id).with_for_update()).all()
    if any(db.scalar(select(InsulationRecallItem.id).where(InsulationRecallItem.install_id==inst.id)) for inst in installs):raise HTTPException(409,'该批次仍有在箱安装已接入其他召回，请先完成换装')
    recall=InsulationRecall(lot_id=lot.id,reason=b.reason.strip(),created_by=u.email);db.add(recall);db.flush()
    for inst in installs:
        db.add(InsulationRecallItem(recall_id=recall.id,install_id=inst.id,hive_id=inst.hive_id,install_state_at_recall=inst.state,state='locked'))
    db.flush()
    mark_reviews(db,recall.id,[inst.id for inst in installs])
    audit(db,u,f'主管召回保温批次 {lot.code}，锁定{len(installs)}笔在箱安装')
    db.commit();return recall

def attach(db,key,b,u):
    lock_season(db)
    recall=require(db,InsulationRecall,key,True)
    if recall.state!='open':raise HTTPException(409,'召回已关闭，不能再接入安装')
    inst=require(db,InsulationInstall,b.install_id,True)
    if inst.lot_id!=recall.lot_id:raise HTTPException(409,'该安装不属于本次召回批次')
    if inst.state not in ['installed','accepted']:raise HTTPException(409,'仅仍在箱上的安装可以接入召回')
    if db.scalar(select(InsulationRecallItem.id).where(InsulationRecallItem.install_id==inst.id)):raise HTTPException(409,'该安装已在召回范围')
    if open_items(db,inst.hive_id,True):raise HTTPException(409,'该箱已有未销项召回，请先完成换装')
    db.add(InsulationRecallItem(recall_id=recall.id,install_id=inst.id,hive_id=inst.hive_id,install_state_at_recall=inst.state,state='locked'))
    db.flush();mark_reviews(db,recall.id,[inst.id])
    audit(db,u,f'召回{key}接入旧安装INS-{inst.id}')
    db.commit();return recall

def close_recall(db,key,b,u):
    lock_season(db)
    recall=require(db,InsulationRecall,key,True)
    if recall.state!='open':raise HTTPException(409,'召回已关闭')
    pending=db.scalar(select(InsulationRecallItem.id).where(InsulationRecallItem.recall_id==key,InsulationRecallItem.state.in_(OPEN_ITEM_STATES)))
    if pending:raise HTTPException(409,'仍有蜂箱未完成合格批次换装并重新验收，不能关闭召回')
    recall.state='closed';audit(db,u,f'关闭召回{key}：{b.note.strip()}')
    db.commit();return recall

def trace_recall(db,key):
    recall=require(db,InsulationRecall,key);lot=require(db,InsulationLot,recall.lot_id)
    items=db.scalars(select(InsulationRecallItem).where(InsulationRecallItem.recall_id==key).order_by(InsulationRecallItem.id)).all()
    result=[]
    for item in items:
        inst=require(db,InsulationInstall,item.install_id);hive=require(db,Hive,item.hive_id)
        rep=db.get(InsulationInstall,item.replacement_install_id) if item.replacement_install_id else None
        replot=require(db,InsulationLot,rep.lot_id) if rep else None
        marks=db.scalars(select(SpringRecallMark).where(SpringRecallMark.recall_id==key,SpringRecallMark.install_id==item.install_id)).all()
        result.append({'item_id':item.id,'hive_id':hive.id,'hive_code':hive.code,'install_id':inst.id,'install_state_at_recall':item.install_state_at_recall,'original_install_state':inst.state,'original_lot_id':lot.id,'original_lot_code':lot.code,'original_units':inst.units,'original_installed_by':inst.installed_by,'original_accepted_by':inst.accepted_by,'original_returned_units':inst.returned_units,'state':item.state,'recovered_units':item.recovered_units,'replacement_install_id':rep.id if rep else None,'replacement_install_state':rep.state if rep else None,'replacement_lot_id':replot.id if replot else None,'replacement_lot_code':replot.code if replot else None,'replacement_accepted_by':rep.accepted_by if rep else '', 'spring_review_ids':[m.review_id for m in marks]})
    return {'recall':{'id':recall.id,'lot_id':lot.id,'lot_code':lot.code,'reason':recall.reason,'state':recall.state,'created_by':recall.created_by,'created_at':recall.created_at},'items':result}

def trace_install(db,key):
    inst=require(db,InsulationInstall,key);lot=require(db,InsulationLot,inst.lot_id)
    item=db.scalar(select(InsulationRecallItem).where((InsulationRecallItem.install_id==key)|(InsulationRecallItem.replacement_install_id==key)).order_by(InsulationRecallItem.id.desc()))
    if not item:return {'install':{'id':inst.id,'lot_id':lot.id,'lot_code':lot.code,'hive_id':inst.hive_id,'units':inst.units,'state':inst.state},'recall':None,'role':None,'item_state':None}
    recall=require(db,InsulationRecall,item.recall_id)
    return {'install':{'id':inst.id,'lot_id':lot.id,'lot_code':lot.code,'hive_id':inst.hive_id,'units':inst.units,'state':inst.state},'recall':{'id':recall.id,'lot_id':recall.lot_id,'state':recall.state,'reason':recall.reason,'created_by':recall.created_by},'role':'replacement' if item.replacement_install_id==key else 'recalled_original','item_state':item.state}
