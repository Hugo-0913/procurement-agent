from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from procurement_agent.agents.config import load_agents_config
from procurement_agent.agents.coordinator import CoordinatorDeps, build_handlers
from procurement_agent.agents.model import build_chat_model
from procurement_agent.config import load_env, load_procurement_config
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

# 静态资源版本号：改动前端文件后必须更新它。
# 浏览器会缓存 /static/*.js，若 HTML 与 JS 版本不匹配，页面按钮会"点了没反应"。
# 改了前端静态资源就把它 +1：浏览器缓存不清会继续跑旧 JS（表现为"点了没反应"）
ASSET_VERSION = "20260923-5"


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
    offline_script: list[str] | None = None,
) -> FastAPI:
    """构造 Web 应用。

    ``offline=None``（默认）表示自动判断：未配置 ``DEEPSEEK_API_KEY`` 时使用内置离线
    模型，保证没有 API key 也能完整跑通演示；显式传 ``False`` 则强制使用真实模型。
    """
    load_env()
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

    if offline:
        # 离线演示：构造单例模型并让工厂始终返回它。
        # 传 offline_script 时按顺序消耗脚本（用于验证"先澄清、后补齐"这类多轮场景）。
        from procurement_agent.agents.offline import OfflineChatModel

        offline_model = OfflineChatModel(
            default_response=offline_response,
            script=list(offline_script) if offline_script else None,
            agent_mode=True,
        )
        model_factory = lambda **overrides: offline_model  # noqa: E731
    else:
        model_factory = build_chat_model
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
    templates.env.globals["asset_version"] = ASSET_VERSION
    app = FastAPI(title="医用耗材采购自动化 Agent 系统")
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
    if ctx.eval_runner is None:
        # 不注入时也要给一个可用的评测运行器，否则评测页点按钮会直接 503
        from procurement_agent.eval.runner import EvalRunner

        ctx.eval_runner = EvalRunner(
            workspace=Path("eval_results") / "web_runs",
            output_path=Path("eval_results") / "web_latest.json",
        )
    app.include_router(build_router(ctx))
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        """静态资源禁用强缓存，避免改完前端后浏览器仍用旧文件。"""
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    app.state.ctx = ctx
    app.state.offline = offline
    return app


def create_demo_app() -> FastAPI:
    """演示入口：强制离线模型，不依赖任何 API key。"""
    return create_app(offline=True)
