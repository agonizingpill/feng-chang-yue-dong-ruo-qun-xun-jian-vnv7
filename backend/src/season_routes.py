from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import session
from .auth import current,editor,admin
from .yard_service import require,audit
from .season_models import ApiaryMove,InsulationLot,InsulationInstall,SpringReview,InsulationRecall,InsulationRecallItem,InsulationQuarantineStock,SpringRecallMark
from .season_schemas import MoveInput,InsulationInput,LotState,InstallInput,VentilationInput,RemoveInput,SpringInput,PassInput,RecallInput,RecallAttachInput,RecallCloseInput,ReplaceInput
from . import move_service,insulation_service,spring_service,recall_service
router=APIRouter()
@router.get('/moves')
def moves(u=Depends(current),db=Depends(session)):return db.scalars(select(ApiaryMove).order_by(ApiaryMove.id.desc())).all()
@router.post('/moves')
def move(b:MoveInput,u=Depends(editor),db=Depends(session)):return move_service.request_move(db,b,u)
@router.post('/moves/{key}/approve')
def approve(key:int,u=Depends(admin),db=Depends(session)):return move_service.transition(db,key,u,'approve')
@router.post('/moves/{key}/complete')
def complete(key:int,u=Depends(editor),db=Depends(session)):return move_service.transition(db,key,u,'complete')
@router.post('/moves/{key}/cancel')
def cancel(key:int,u=Depends(editor),db=Depends(session)):return move_service.transition(db,key,u,'cancel')
@router.get('/insulation-lots')
def lots(u=Depends(current),db=Depends(session)):return db.scalars(select(InsulationLot).order_by(InsulationLot.id)).all()
@router.post('/insulation-lots')
def lot(b:InsulationInput,u=Depends(editor),db=Depends(session)):
    row=InsulationLot(**b.model_dump());db.add(row);audit(db,u,'登记保温物料');db.commit();return row
@router.put('/insulation-lots/{key}/state')
def state(key:int,b:LotState,u=Depends(admin),db=Depends(session)):
    recall_service.lock_season(db)
    row=require(db,InsulationLot,key,True);row.state=b.state;audit(db,u,'保温物料隔离状态');db.commit();return row
@router.get('/insulation-installs')
def installs(u=Depends(current),db=Depends(session)):return db.scalars(select(InsulationInstall).order_by(InsulationInstall.id.desc())).all()
@router.get('/insulation-installs/{key}/trace')
def install_trace(key:int,u=Depends(current),db=Depends(session)):return recall_service.trace_install(db,key)
@router.post('/insulation-installs')
def install(b:InstallInput,u=Depends(editor),db=Depends(session)):return insulation_service.install(db,b,u)
@router.put('/insulation-installs/{key}/ventilation')
def ventilation(key:int,b:VentilationInput,u=Depends(editor),db=Depends(session)):return insulation_service.change(db,key,b,u,'ventilation')
@router.post('/insulation-installs/{key}/accept')
def accept(key:int,u=Depends(admin),db=Depends(session)):return insulation_service.change(db,key,None,u,'accept')
@router.post('/insulation-installs/{key}/remove')
def remove(key:int,b:RemoveInput,u=Depends(editor),db=Depends(session)):return insulation_service.change(db,key,b,u,'remove')
@router.post('/insulation-installs/replace')
def replace(b:ReplaceInput,u=Depends(editor),db=Depends(session)):return insulation_service.replace(db,b,u)
@router.get('/insulation-recalls')
def recalls(u=Depends(current),db=Depends(session)):return db.scalars(select(InsulationRecall).order_by(InsulationRecall.id.desc())).all()
@router.get('/insulation-recalls/{key}')
def recall(key:int,u=Depends(current),db=Depends(session)):return recall_service.trace_recall(db,key)
@router.get('/insulation-recall-items')
def recall_items(u=Depends(current),db=Depends(session)):return db.scalars(select(InsulationRecallItem).order_by(InsulationRecallItem.id)).all()
@router.get('/insulation-quarantine')
def quarantine(u=Depends(current),db=Depends(session)):return db.scalars(select(InsulationQuarantineStock).order_by(InsulationQuarantineStock.lot_id)).all()
@router.get('/spring-recall-marks')
def spring_marks(u=Depends(current),db=Depends(session)):return db.scalars(select(SpringRecallMark).order_by(SpringRecallMark.id)).all()
@router.post('/insulation-recalls')
def open_recall(b:RecallInput,u=Depends(admin),db=Depends(session)):return recall_service.open_recall(db,b,u)
@router.post('/insulation-recalls/{key}/attach')
def attach(key:int,b:RecallAttachInput,u=Depends(admin),db=Depends(session)):return recall_service.attach(db,key,b,u)
@router.post('/insulation-recalls/{key}/close')
def close_recall(key:int,b:RecallCloseInput,u=Depends(admin),db=Depends(session)):return recall_service.close_recall(db,key,b,u)
@router.get('/spring-reviews')
def reviews(u=Depends(current),db=Depends(session)):return db.scalars(select(SpringReview).order_by(SpringReview.id.desc())).all()
@router.post('/spring-reviews')
def review(b:SpringInput,u=Depends(editor),db=Depends(session)):return spring_service.record(db,b,u)
@router.post('/spring-reviews/{key}/pass')
def pass_review(key:int,b:PassInput,u=Depends(admin),db=Depends(session)):return spring_service.pass_review(db,key,b,u)
