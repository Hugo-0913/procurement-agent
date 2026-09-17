from __future__ import annotations

from pathlib import Path
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from procurement_agent.agents.config import load_agents_config
from procurement_agent.agents.coordinator import CoordinatorDeps, build_handlers
from procurement_agent.agents.model import build_chat_model
from procurement_agent.agents.offline import offline_model_factory
from procurement_agent.config import load_procurement_config
from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.faults import FaultRegistry
from procurement_agent.erp.repository import ErpRepository
from procurement_agent.memory.store import MemoryStore
from procurement_agent.middleware.context_summarizer import ContextSummarizer
from procurement_agent.sandbox.policy import PolicyEngine
from procurement_agent.skills_loader import SkillRegistry
from procurement_agent.state.graph import TaskRunner, build_stage_graph
from procurement_agent.state.store import TaskStore
from procurement_agent.web.routes import WebContext, build_router

WEB_ROOT = Path(__file__).parent
logger = logging.getLogger(__name__)


def default_db_path() -> Path:
    return Path("data") / "procurement.db"


def create_app(
    db_path: Path | str | None = None,
    *,
    offline: bool | None = None,
    config_path: Path | None = None,
    agents_config_path: Path | None = None,
    skills_root: Path | None = None,
    eval_runner=None,
    offline_response: str | None = None,
) -> FastAPI:
    """构造 Web 应用。

    ``offline=None``（默认）表示自动判断：未配置 ``DEEPSEEK_API_KEY`` 时使用内置离线
    模型，保证没有 API key 也能完整跑通演示；显式传 ``False`` 则强制使用真实模型。
    """
    if offline is None:
        offline = not os.environ.get("DEEPSEEK_API_KEY")
        if offline:
            logger.warning(
                "未检测到 DEEPSEEK_API_KEY，已自动切换到离线演示模型；"
                "配置该环境变量后重启即可使用真实模型。"
            )
    config = load_procurement_config(config_path)
    agents_config = load_agents_config(agents_config_path)
    target_db = Path(db_path) if db_path is not None else default_db_path()
    engine = init_db(target_db)
    seed_demo_data(engine)

    model_factory = (
        offline_model_factory(offline_response) if offline else build_chat_model
    )
    faults = FaultRegistry(engine)
    repo = ErpRepository(engine, faults)
    store = TaskStore(engine)
    skills = SkillRegistry(skills_root) if skills_root is not None else SkillRegistry()
    memory = MemoryStore(engine, config)
    summarizer = ContextSummarizer(config, model_factory)
    policy = PolicyEngine(config)

    deps = CoordinatorDeps(
        repo=repo,
        store=store,
        config=config,
        agents_config=agents_config,
        skills=skills,
        policy=policy,
        model_factory=model_factory,
        memory=memory,
        summarizer=summarizer,
    )
    graph = build_stage_graph(store, build_handlers(deps), config)
    runner = TaskRunner(store, graph)

    templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))
    app = FastAPI(title="耗材采购自动化 Agent 系统")
    ctx = WebContext(
        config=config,
        repo=repo,
        store=store,
        runner=runner,
        faults=faults,
        skills=skills,
        memory=memory,
        templates=templates,
        eval_runner=eval_runner,
        offline=offline,
    )
    app.include_router(build_router(ctx))
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")
    app.state.ctx = ctx
    app.state.offline = offline
    return app


def create_demo_app() -> FastAPI:
    """演示入口：强制离线模型，不依赖任何 API key。"""
    return create_app(offline=True)
