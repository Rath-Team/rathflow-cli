"""workflow：工作流定义与删除。"""

from __future__ import annotations

import typer

from .. import output
from ..commands._common import (
    BODY_FILE_OPT,
    BODY_OPT,
    PAGE_SIZE_OPT,
    PAGE_TOKEN_OPT,
    body_of,
    pagination,
)
from ..state import current

app = typer.Typer(no_args_is_help=True, help="工作流")

COLUMNS = [
    ("WORKFLOW ID", "workflowId"),
    ("标题", "title"),
    ("状态", "status"),
    ("更新时间", "updatedAt"),
]


@app.command("list")
def list_(
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """列工作流。"""
    st = current()
    payload = st.client().call("workflow.ListWorkflows", query=pagination(page_size or 50, page_token))
    output.emit_items(payload, items_key="workflows", columns=COLUMNS, json_out=st.json_out)


@app.command("get")
def get(workflow_id: str = typer.Argument(...)) -> None:
    """工作流详情。"""
    st = current()
    payload = st.client().call("workflow.GetWorkflow", path_params={"workflow_id": workflow_id})
    output.emit_object(payload, json_out=st.json_out)


@app.command("counts")
def counts() -> None:
    """每个 project 的存活工作流数（服务端不返回 0 的行 = 没有）。"""
    st = current()
    payload = st.client().call("workflow.CountWorkflowsByProject")
    output.emit_items(
        payload,
        items_key="counts",
        columns=[("PROJECT ID", "projectId"), ("数量", "count")],
        json_out=st.json_out,
    )


@app.command("create")
def create(
    title: str = typer.Option(None, "--title", "-t"),
    body: str = BODY_OPT,
    body_file: str = BODY_FILE_OPT,
) -> None:
    """建工作流（图定义用 --body 传）。"""
    st = current()
    payload_body = body_of(body, body_file) or {}
    if title:
        payload_body.setdefault("title", title)
    payload = st.client().call("workflow.CreateWorkflow", body=payload_body)
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(payload.get("workflowId") or "")


@app.command("delete")
def delete(
    workflow_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """删工作流（连同其会话与沙箱；响应会报删了多少）。"""
    st = current()
    if not yes:
        typer.confirm(f"确认删除工作流 {workflow_id}？其下会话与沙箱一并清理", abort=True)
    payload = st.client().call("workflow.DeleteWorkflow", path_params={"workflow_id": workflow_id})
    if st.json_out:
        output.emit_json(payload)
        return
    typer.echo(
        f"已删除；清理会话 {payload.get('sessionsDeleted', 0)} 个、"
        f"沙箱 {payload.get('sandboxesTerminated', 0)} 个"
    )
