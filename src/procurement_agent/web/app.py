from __future__ import annotations

from pathlib import Path

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


def default_db_path() -> Path:
    return Path("data") / "procurement.db"


def create_app(
    db_path: Path | str | None = None,
    *,
    offline: bool = False,
    config_path: Path | None = None,
    agents_config_path: Path | None = None,
    skills_root: Path | None = None,
    eval_runner=None,
    offline_response: str | None = None,
) -> FastAPI:
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
    )
    app.include_router(build_router(ctx))
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")
    app.state.ctx = ctx
    return app
