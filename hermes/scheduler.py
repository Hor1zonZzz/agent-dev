"""In-process scheduler for Hermes daily tasks + nightly self-planner."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal

from loguru import logger

from core.trace import RunMeta, TraceRecorder, get_default_trace_sink

DEFAULT_SCHEDULE: list[tuple[str, time]] = [
    ("morning", time(8, 0)),
    ("noon", time(12, 0)),
    ("evening", time(21, 0)),
]

PLANNER_TIME: time = time(23, 0)


@dataclass(frozen=True)
class ScheduledEvent:
    kind: Literal["planner", "hermes_task", "hermes_slot"]
    when: datetime
    payload: tuple[str, str] | str | None = None


def _candidates_for_day(day: date) -> list[ScheduledEvent]:
    from hermes.plan import read_plan

    events: list[ScheduledEvent] = [
        ScheduledEvent(kind="planner", when=datetime.combine(day, PLANNER_TIME))
    ]

    plan = read_plan(day)
    if plan is not None:
        for task in plan.tasks:
            hh, mm = task.time.split(":")
            events.append(
                ScheduledEvent(
                    kind="hermes_task",
                    when=datetime.combine(day, time(int(hh), int(mm))),
                    payload=(task.title, task.instruction),
                )
            )
    else:
        for slot_name, slot_time in DEFAULT_SCHEDULE:
            events.append(
                ScheduledEvent(
                    kind="hermes_slot",
                    when=datetime.combine(day, slot_time),
                    payload=slot_name,
                )
            )

    return events


def _next_event(now: datetime) -> ScheduledEvent:
    for offset in (0, 1, 2):
        day = now.date() + timedelta(days=offset)
        future = [event for event in _candidates_for_day(day) if event.when > now]
        if future:
            future.sort(key=lambda event: event.when)
            return future[0]
    raise RuntimeError("no upcoming scheduled events (unexpected)")


def _label(event: ScheduledEvent) -> str:
    if event.kind == "planner":
        return "planner"
    if event.kind == "hermes_task":
        assert isinstance(event.payload, tuple)
        return f"task '{event.payload[0]}'"
    return f"slot {event.payload}"


def _recorder_for_event(event: ScheduledEvent) -> TraceRecorder:
    payload: dict[str, object] = {
        "scheduled_for": event.when.isoformat(timespec="minutes"),
        "label": _label(event),
    }
    if event.kind == "hermes_task":
        assert isinstance(event.payload, tuple)
        payload["title"] = event.payload[0]
    elif event.kind == "hermes_slot":
        payload["slot"] = event.payload

    return TraceRecorder(
        get_default_trace_sink(),
        RunMeta(
            run_kind=event.kind,
            source="scheduler",
            context=payload,
        ),
    )


async def _run_event(event: ScheduledEvent, recorder: TraceRecorder) -> tuple[str, dict[str, object]]:
    if event.kind == "planner":
        from hermes.planner import run_planner

        try:
            ok = await run_planner(trace_sink=get_default_trace_sink(), recorder=recorder)
            logger.info("[hermes-cron] planner 完成 (ok={})", ok)
            return ("ok" if ok else "error", {"ok": ok})
        except Exception as exc:
            logger.exception("[hermes-cron] planner 异常")
            return ("error", {"error_type": type(exc).__name__, "error_message": str(exc)})

    if event.kind == "hermes_task":
        from hermes.runner import run_single_task

        assert isinstance(event.payload, tuple)
        title, instruction = event.payload
        try:
            ok = await asyncio.to_thread(
                run_single_task,
                title,
                instruction,
                trace_recorder=recorder,
            )
            logger.info("[hermes-cron] task '{}' 完成 (ok={})", title, ok)
            return ("ok" if ok else "error", {"title": title, "ok": ok})
        except Exception as exc:
            logger.exception("[hermes-cron] task '{}' 异常", title)
            return (
                "error",
                {"title": title, "error_type": type(exc).__name__, "error_message": str(exc)},
            )

    from hermes.runner import run_slot

    assert isinstance(event.payload, str)
    slot_name = event.payload
    try:
        exit_code = await asyncio.to_thread(run_slot, slot_name, trace_recorder=recorder)
        logger.info("[hermes-cron] {} 完成 (exit={})", slot_name, exit_code)
        return ("ok" if exit_code == 0 else "error", {"slot": slot_name, "exit_code": exit_code})
    except Exception as exc:
        logger.exception("[hermes-cron] {} 异常", slot_name)
        return (
            "error",
            {"slot": slot_name, "error_type": type(exc).__name__, "error_message": str(exc)},
        )


async def _scheduler_loop() -> None:
    os.environ.setdefault("HERMES_MODEL", "deepseek-chat")

    while True:
        event = _next_event(datetime.now())
        wait = (event.when - datetime.now()).total_seconds()
        label = _label(event)
        recorder = _recorder_for_event(event)

        await recorder.emit(
            lane="scheduler",
            type="schedule.next_computed",
            status="ok",
            summary=f"next scheduled event: {label}",
            payload={
                "wait_seconds": wait,
                "scheduled_for": event.when.isoformat(timespec="minutes"),
            },
        )

        logger.info(
            "[hermes-cron] 下一次: {} at {} (在 {:.0f} 秒后)",
            label, event.when.strftime("%Y-%m-%d %H:%M"), wait,
        )
        await asyncio.sleep(max(1.0, wait))

        await recorder.emit(
            lane="scheduler",
            type="schedule.fired",
            status="ok",
            summary=f"scheduled event fired: {label}",
            payload={"fired_at": datetime.now().isoformat(timespec="seconds")},
        )
        status, payload = await _run_event(event, recorder)
        await recorder.emit(
            lane="scheduler",
            type="schedule.finished",
            status=status,
            summary=f"scheduled event finished: {label}",
            payload=payload,
        )


def start() -> asyncio.Task:
    return asyncio.create_task(_scheduler_loop(), name="anna-hermes-cron")


async def stop(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def _standalone() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logger.info("[hermes-cron] standalone scheduler started (Ctrl+C to stop)")
    task = start()
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(_standalone())
    except KeyboardInterrupt:
        logger.info("[hermes-cron] 已停止。")
