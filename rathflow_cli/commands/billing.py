"""billing：订阅、用量与发票（只读）。"""

from __future__ import annotations

import typer

from .. import output
from ..commands._common import PAGE_SIZE_OPT, PAGE_TOKEN_OPT, pagination
from ..state import current

app = typer.Typer(no_args_is_help=True, help="订阅 / 用量 / 发票")


@app.command("subscription")
def subscription(
    project_id: str = typer.Option(None, "--project-id", help="缺省用当前作用域项目"),
) -> None:
    """当前订阅。"""
    st = current()
    payload = st.client().call(
        "billing.GetSubscription", query={"project_id": project_id or st.project}
    )
    output.emit_object(payload, json_out=st.json_out)


@app.command("usage")
def usage(
    project_id: str = typer.Option(None, "--project-id"),
    start: str = typer.Option(None, "--start", help="RFC3339，如 2026-09-01T00:00:00Z"),
    end: str = typer.Option(None, "--end", help="RFC3339"),
    metrics: str = typer.Option(None, "--metrics", help="逗号分隔的指标名"),
) -> None:
    """用量汇总。"""
    st = current()
    query = {
        "project_id": project_id or st.project,
        "start_time": start,
        "end_time": end,
        "metrics": metrics,
    }
    payload = st.client().call("billing.GetUsage", query=query)
    output.emit_table(
        payload.get("usages") or [],
        [("指标", "metric"), ("用量", "units")],
        json_out=st.json_out,
    )


@app.command("invoices")
def invoices(
    project_id: str = typer.Option(None, "--project-id"),
    page_size: int = PAGE_SIZE_OPT,
    page_token: str = PAGE_TOKEN_OPT,
) -> None:
    """发票列表。"""
    st = current()
    query = pagination(page_size or 20, page_token, {"project_id": project_id or st.project})
    payload = st.client().call("billing.ListInvoices", query=query)
    output.emit_items(
        payload,
        items_key="invoices",
        columns=[
            ("INVOICE ID", "invoiceId"),
            ("编号", "number"),
            ("周期", "periodStart"),
            ("金额", "amountMinor"),
            ("币种", "currency"),
            ("状态", "status"),
        ],
        json_out=st.json_out,
    )
