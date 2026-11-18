from datetime import date
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
class Input(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
class MoveInput(Input):
    hive_id:int
    destination:str=Field(min_length=2,max_length=50)
    move_date:date
    health_note:str=Field(min_length=5,max_length=400)
class InsulationInput(Input):
    code:str=Field(min_length=2,max_length=50)
    available_units:int=Field(ge=1,le=10000)
class LotState(Input):
    state:Literal['active','quarantine']
class InstallInput(Input):
    hive_id:int
    lot_id:int
    units:int=Field(ge=1,le=100)
    ventilation_checked:bool
class VentilationInput(Input):
    ventilation_checked:bool
class RemoveInput(Input):
    reusable_units:int=Field(ge=0,le=100)
class SpringInput(Input):
    hive_id:int
    opening_weight:float=Field(gt=0,le=100)
    frames:int=Field(ge=0,le=20)
    queen_seen:bool
    mortality_pct:float=Field(ge=0,le=100)
class PassInput(Input):
    rescue_care_id:int|None=None
    resolution:str=Field(min_length=5,max_length=400)
class RecallInput(Input):
    lot_id:int
    reason:str=Field(min_length=5,max_length=300)
    @field_validator('reason')
    @classmethod
    def reason_required(cls,v):
        if len(v.strip())<5:raise ValueError('召回依据至少5字')
        return v.strip()
class RecallAttachInput(Input):
    install_id:int
class RecallCloseInput(Input):
    note:str=Field(min_length=5,max_length=300)
    @field_validator('note')
    @classmethod
    def note_required(cls,v):
        if len(v.strip())<5:raise ValueError('召回关闭说明至少5字')
        return v.strip()
class ReplaceInput(Input):
    hive_id:int
    lot_id:int
    units:int=Field(ge=1,le=100)
    reusable_units:int=Field(ge=0,le=100)
    ventilation_checked:bool=False
