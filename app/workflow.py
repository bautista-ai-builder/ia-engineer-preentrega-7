"""Grafo de servicio con punto de aprobación humana antes de tareas sensibles."""

import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.graph import run as run_team

SENSITIVE = re.compile(
    r"\b(borrar|eliminar|exportar|publicar|enviar|modificar|delete|send)\b", re.I
)


class ServiceState(TypedDict, total=False):
    question: str
    require_approval: bool
    approved: bool
    status: str
    answer: str
    route_history: list[str]
    history: list[dict[str, str]]


def build_workflow(*, checkpointer, team_graph=None):
    def assess(state: ServiceState) -> ServiceState:
        needed = bool(state.get("require_approval")) or bool(SENSITIVE.search(state["question"]))
        return {
            "require_approval": needed,
            "approved": False,
            "status": "pending" if needed else "running",
        }

    def gate(state: ServiceState) -> ServiceState:
        decision = interrupt({"question": state["question"], "reason": "Revisión humana requerida"})
        return {
            "approved": decision is True,
            "status": "running" if decision is True else "rejected",
        }

    def execute(state: ServiceState) -> ServiceState:
        result = run_team(state["question"], graph=team_graph)
        answer = result["answer"]
        return {
            "answer": answer,
            "route_history": result["route_history"],
            "status": "completed",
            "history": [
                *state.get("history", []),
                {"question": state["question"], "answer": answer},
            ],
        }

    def reject(state: ServiceState) -> ServiceState:
        return {"answer": "Solicitud rechazada por el revisor.", "status": "rejected"}

    builder = StateGraph(ServiceState)
    builder.add_node("assess", assess)
    builder.add_node("gate", gate)
    builder.add_node("execute", execute)
    builder.add_node("reject", reject)
    builder.add_edge(START, "assess")
    builder.add_conditional_edges(
        "assess", lambda s: "gate" if s["require_approval"] else "execute"
    )
    builder.add_conditional_edges("gate", lambda s: "execute" if s["approved"] else "reject")
    builder.add_edge("execute", END)
    builder.add_edge("reject", END)
    return builder.compile(checkpointer=checkpointer)
