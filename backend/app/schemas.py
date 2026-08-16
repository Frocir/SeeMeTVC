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
    config_json: dict = Field(default_factory=dict)


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
    config_json: dict | None = None


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
    config_json: dict = Field(default_factory=dict)
    capabilities: dict = Field(default_factory=dict)

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
    capabilities: dict = Field(default_factory=dict)


class ChannelCapabilitiesOut(BaseModel):
    id: int
    name: str
    provider: str
    model_id: str
    kind: str
    capabilities: dict = Field(default_factory=dict)


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


class WorkflowExpandScenesIn(BaseModel):
    source_node_id: str
    mode: str = "with_image"
    create_images: bool | None = None
    create_tts: bool | None = None
    create_subtitles: bool | None = None
    layout: str = "horizontal"


class WorkflowExpandScenesOut(BaseModel):
    workflow_id: int
    graph: dict
    created_node_ids: list[str]
    created_edge_ids: list[str]
    final_node_id: str | None = None


class WorkflowOut(BaseModel):
    id: int
    name: str
    brand: str = "GlamPilot"
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
    work_mode: str = "auto"
    text: str = Field(min_length=1, max_length=8000)
    selected_node_id: str = ""
    viewport: AgentViewportIn | None = None


class AgentSessionPatchIn(BaseModel):
    skill_id: str | None = None
    work_mode: str | None = None
    clear_chat: bool = False


class AgentResumeIn(BaseModel):
    workflow_id: int
    accept: bool = True
    action: str = ""
    selected_node_id: str = ""
    viewport: AgentViewportIn | None = None


class AssetVersionOut(BaseModel):
    id: int
    workflow_id: int
    run_id: int | None = None
    node_id: str = ""
    node_type: str = ""
    kind: str
    url: str = ""
    thumbnail_url: str = ""
    text: str = ""
    prompt: str = ""
    model_provider: str = ""
    model_name: str = ""
    channel_id: int | None = None
    params: dict = {}
    cost: float = 0.0
    status: str = "succeeded"
    error_message: str = ""
    favorite: bool = False
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class AssetVersionListOut(BaseModel):
    items: list[AssetVersionOut]
    total: int
    limit: int
    offset: int


class AssetVersionPatchIn(BaseModel):
    favorite: bool | None = None


class AssetVersionBulkDeleteIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class AssetVersionSendIn(BaseModel):
    x: float | None = None
    y: float | None = None


class AssetVersionSendOut(BaseModel):
    node_id: str
    node_type: str
    graph: dict
