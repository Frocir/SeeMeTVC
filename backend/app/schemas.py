from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    display_name: str
    role: str
    balance: float
    is_active: bool

    model_config = {"from_attributes": True}


class MeOut(UserOut):
    balance_unit: str


class ChannelCreate(BaseModel):
    name: str
    provider: str = "ark"
    kind: str = "video"
    base_url: str = ""
    api_key: str = ""
    model_id: str
    upstream_model: str
    cost_per_second: float = 1.0
    priority: int = 0
    enabled: bool = True
    remark: str = ""


class ChannelUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    kind: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = None
    upstream_model: str | None = None
    cost_per_second: float | None = None
    priority: int | None = None
    enabled: bool | None = None
    remark: str | None = None


class ChannelOut(BaseModel):
    id: int
    name: str
    provider: str
    kind: str = "video"
    base_url: str
    model_id: str
    upstream_model: str
    cost_per_second: float
    priority: int
    enabled: bool
    remark: str
    # Masked for admin list safety
    api_key_masked: str

    model_config = {"from_attributes": True}


class ChannelProbeOut(BaseModel):
    ok: bool
    message: str
    latency_ms: int
    detail: str = ""


class ModelOptionOut(BaseModel):
    model_id: str
    cost_per_second: float
    provider: str
    kind: str = "video"
    label: str = ""
    duration_min: int = 2
    duration_max: int = 30
    supports_audio: bool = False
    supports_image: bool = True


class GenerateIn(BaseModel):
    model_id: str
    prompt: str = Field(min_length=1, max_length=4000)
    image_url: str | None = None
    duration_seconds: int = Field(default=5, ge=2, le=30)


class JobOut(BaseModel):
    id: int
    model_id: str
    prompt: str
    image_url: str | None
    duration_seconds: int
    status: str
    cost: float
    balance_after: float | None
    result_url: str | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ParallelQuotaOut(BaseModel):
    max_parallel: int
    active: int
    available: int


class AdminSetBalanceIn(BaseModel):
    balance: float = Field(ge=0)


class AdminUserOut(UserOut):
    pass


class BalanceEntryOut(BaseModel):
    id: int
    amount: float
    balance_after: float
    kind: str
    title: str
    ref_type: str
    ref_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Workflow (ComfyUI-like DAG) ──────────────────────────────────────────────


class WorkflowGraphIn(BaseModel):
    """DAG graph, optionally wrapping a Liblib WorkflowProject envelope."""

    model_config = ConfigDict(extra="allow")

    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    kind: str | None = None
    project: dict | None = None


class WorkflowCreateIn(BaseModel):
    name: str = Field(default="未命名项目", max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    graph: WorkflowGraphIn | None = None


class WorkflowUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    graph: WorkflowGraphIn | None = None


class WorkflowOut(BaseModel):
    id: int
    name: str
    brand: str = "SeeMe"
    cover_url: str | None = None
    graph: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectAssetOut(BaseModel):
    id: int
    workflow_id: int
    kind: str
    url: str
    filename: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectAssetCreateIn(BaseModel):
    url: str
    kind: str | None = None
    filename: str = ""


class ProjectAssetCopyIn(BaseModel):
    target_workflow_id: int


class WorkflowRunCreateIn(BaseModel):
    workflow_id: int | None = None
    graph: WorkflowGraphIn | None = None
    name: str | None = Field(default=None, max_length=200)
    # Optional: only execute these node ids (serial queue / single-node).
    target_ids: list[str] | None = None


class WorkflowNodeStateOut(BaseModel):
    status: str
    output: dict | None = None
    error: str | None = None
    cost: float = 0.0


class WorkflowRunOut(BaseModel):
    id: int
    workflow_id: int | None
    status: str
    graph: dict
    node_states: dict
    cost: float
    balance_after: float | None
    result_url: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentViewportIn(BaseModel):
    x: float = 400
    y: float = 280


class AgentChatIn(BaseModel):
    workflow_id: int
    model_id: str = ""
    skill_id: str = ""
    text: str = Field(min_length=1, max_length=8000)
    selected_node_id: str = ""
    viewport: AgentViewportIn | None = None


class AgentResumeIn(BaseModel):
    workflow_id: int
    accept: bool = True
    selected_node_id: str = ""
    viewport: AgentViewportIn | None = None
