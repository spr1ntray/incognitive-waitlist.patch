from __future__ import annotations

from typing import Any

from soft_hub.sdk import CancelledError, HubAccount, HubContext

from plugin.client import normalize_email, submit_waitlist
from plugin.proxy import proxy_to_url

PRIMARY_KIND = "account_snapshot"


def run(context: HubContext) -> dict[str, Any]:
    if context.action_id != "register_waitlist":
        raise ValueError("unsupported_action")

    timeout_seconds = _int_option(context.options, "timeout_seconds", 30, 5, 120)

    counters = {
        "total": len(context.accounts),
        "succeeded": 0,
        "failed": 0,
        "blocked": 0,
        "cancelled": 0,
        "needs_attention": 0,
    }

    def process(account: HubAccount) -> str:
        return _process_account(context, account, timeout_seconds)

    outcomes = context.map_accounts(process)
    for status in outcomes:
        counters[status] = counters.get(status, 0) + 1
    return counters


def _process_account(
    context: HubContext,
    account: HubAccount,
    timeout_seconds: int,
) -> str:
    context.check_cancelled()
    context.account_state(
        account.id,
        status="running",
        stage="preflight",
        progress=0.05,
        message="Проверяем email и proxy",
    )

    write_sent = False
    try:
        try:
            email = normalize_email(account.secret("email"))
            proxy = account.secret("proxy")
            proxy_to_url(proxy)
        except (KeyError, ValueError):
            _finish(
                context,
                account,
                status="blocked",
                stage="preflight",
                message="Нет email или proxy, либо они неверные",
                result_status="blocked",
                data={
                    "outcome": "blocked",
                    "http_status": 0,
                    "error_code": "missing_or_invalid_credentials",
                },
            )
            return "blocked"

        context.check_cancelled()
        context.account_state(
            account.id,
            status="running",
            stage="submitting",
            progress=0.40,
            message="Отправляем заявку в waitlist",
        )

        write_sent = True
        status_code = submit_waitlist(
            email=email,
            proxy=proxy,
            timeout_seconds=timeout_seconds,
        )
        write_sent = False

        if 200 <= status_code < 300:
            context.account_state(
                account.id,
                status="running",
                stage="confirming",
                progress=0.90,
                message="Ответ получен",
            )
            _finish(
                context,
                account,
                status="succeeded",
                stage="completed",
                message="Email записан в waitlist",
                result_status="succeeded",
                data={
                    "outcome": "submitted",
                    "http_status": status_code,
                    "error_code": "",
                },
                progress=1.0,
            )
            return "succeeded"

        _finish(
            context,
            account,
            status="failed",
            stage="failed",
            message="Сервис вернул неожиданный ответ",
            result_status="failed",
            data={
                "outcome": "failed",
                "http_status": status_code,
                "error_code": "unexpected_http_status",
            },
        )
        return "failed"

    except CancelledError:
        if write_sent:
            _finish(
                context,
                account,
                status="needs_attention",
                stage="needs_reconciliation",
                message="Остановка во время отправки — сверьте waitlist вручную",
                result_status="needs_attention",
                data={
                    "outcome": "needs_attention",
                    "http_status": 0,
                    "error_code": "cancelled_after_submit",
                },
            )
            return "needs_attention"
        context.account_state(
            account.id,
            status="cancelled",
            stage="cancelled",
            message="Остановлено до отправки",
        )
        return "cancelled"
    except Exception:
        if write_sent:
            _finish(
                context,
                account,
                status="needs_attention",
                stage="needs_reconciliation",
                message="Сбой после отправки — сверьте waitlist вручную",
                result_status="needs_attention",
                data={
                    "outcome": "needs_attention",
                    "http_status": 0,
                    "error_code": "ambiguous_after_submit",
                },
            )
            return "needs_attention"
        _finish(
            context,
            account,
            status="failed",
            stage="failed",
            message="Не удалось отправить заявку",
            result_status="failed",
            data={
                "outcome": "failed",
                "http_status": 0,
                "error_code": "request_failed",
            },
        )
        return "failed"


def _finish(
    context: HubContext,
    account: HubAccount,
    *,
    status: str,
    stage: str,
    message: str,
    result_status: str,
    data: dict[str, Any],
    progress: float | None = None,
) -> None:
    context.result(
        f"{account.label}: {message}",
        kind=PRIMARY_KIND,
        status=result_status,
        account_id=account.id,
        data=data,
    )
    kwargs: dict[str, Any] = {
        "status": status,
        "stage": stage,
        "message": message,
    }
    if progress is not None:
        kwargs["progress"] = progress
    context.account_state(account.id, **kwargs)


def _int_option(
    options: dict[str, Any],
    name: str,
    default: int,
    low: int,
    high: int,
) -> int:
    value = options.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid_{name}")
    if not low <= value <= high:
        raise ValueError(f"invalid_{name}")
    return value
