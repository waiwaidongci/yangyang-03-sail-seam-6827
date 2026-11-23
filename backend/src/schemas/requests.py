from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.constants.enums import Decision


class Credentials(BaseModel):
    email: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)


class PlanBatchInput(BaseModel):
    batch_no: str = Field(min_length=1, max_length=96)
    stage1_count: int = Field(ge=2, le=200)
    stage2_count: int = Field(ge=2, le=200)

    @field_validator('batch_no')
    @classmethod
    def meaningful_batch(cls, value):
        if not value.strip():
            raise ValueError('请填写工票批号')
        return value.strip()


class CreatePlan(BaseModel):
    title: str = Field(max_length=120)
    parameters: dict = Field(default_factory=dict)
    batches: list[PlanBatchInput] = Field(default_factory=list, max_length=100)
    run_first: bool = True

    @field_validator('title')
    @classmethod
    def meaningful_title(cls, value):
        if not value.strip():
            raise ValueError('请填写方案名称')
        return value.strip()

    @field_validator('batches')
    @classmethod
    def two_stage_plan(cls, value):
        if not value:
            raise ValueError('请至少登记一张工票')
        for item in value:
            if item.stage1_count < 2 or item.stage2_count < 2:
                raise ValueError(f'{item.batch_no} 两次抽检都至少 2 片才能做精确检验')
        return value


class SupplementCreate(BaseModel):
    plan_id: int = Field(gt=0)
    batch_no: str = Field(min_length=1, max_length=96)


class SupplementAppend(BaseModel):
    records: list[dict] = Field(default_factory=list, max_length=200)
    observation_ids: list[int] = Field(default_factory=list, max_length=200)

    @field_validator('observation_ids')
    @classmethod
    def distinct_ids(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('补抽试片编号重复')
        return value

    @field_validator('records')
    @classmethod
    def one_mode(cls, value, info):
        if value and info.data.get('observation_ids'):
            raise ValueError('请选择台账已有试片，或录入新试片，不要同时提交')
        return value


class ReviewInput(BaseModel):
    decision: Decision
    note: str = Field(min_length=2, max_length=1000)

    @field_validator('note')
    @classmethod
    def meaningful_note(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('请填写复核依据')
        return value.strip()


class ScheduleInput(BaseModel):
    run_id: int = Field(gt=0)
    recipient: str = Field(min_length=2, max_length=100)
    interval_minutes: int = Field(ge=1, le=10080)
    start_at: datetime | None = None

    @field_validator('recipient')
    @classmethod
    def meaningful_recipient(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('请填写收件组')
        return value.strip()

    @field_validator('start_at')
    @classmethod
    def absolute_time(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError('首次分发时间必须包含时区')
        return value
