"""Supervisor LangGraph que deriva investigación y análisis a especialistas."""

import os
import re
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.tools import buscar_documentacion, calcular_variacion


class RouteDecision(BaseModel):
    next_agent: Literal["researcher", "analyst", "finish"]
    reason: str = Field(description="Motivo breve de la decisión")


class TeamState(TypedDict, total=False):
    question: str
    messages: list
    next_agent: str
    task_completed: bool
    research_output: str
    analysis_output: str
    visited: list[str]
    route_history: list[str]
    answer: str


def _model():
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Falta OPENAI_API_KEY; completar .env")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=os.getenv("CHAT_MODEL", "gpt-4o-mini"), temperature=0)


def _default_router(state: TeamState) -> RouteDecision:
    model = _model().with_structured_output(RouteDecision)
    return model.invoke(
        "Eres supervisor. Elige researcher para preguntas que exigen fuentes técnicas; "
        "analyst para cálculos o comparación numérica; finish cuando ya haya evidencia "
        "suficiente. Puedes usar ambos especialistas en turnos sucesivos. "
        "No repitas especialistas ya visitados.\n"
        f"Pregunta: {state['question']}\nVisitados: {state.get('visited', [])}\n"
        f"Investigación: {state.get('research_output', '')}\n"
        f"Análisis: {state.get('analysis_output', '')}"
    )


def _default_writer(role: str, question: str, evidence: str) -> str:
    reply = _model().invoke(
        f"Eres {role}. Responde en español usando solo esta evidencia. "
        "Si falta información, dilo. No inventes cifras ni fuentes.\n"
        f"Pregunta: {question}\nEvidencia:\n{evidence}"
    )
    return str(reply.content)


def build_graph(*, router=None, writer=None, checkpointer=None):
    """Inyección de router/writer permite verificar el flujo sin consumir API."""
    decide = router or _default_router
    compose = writer or _default_writer

    def supervisor(state: TeamState) -> TeamState:
        visited = state.get("visited", [])
        if len(visited) >= 2:
            choice = "finish"
        else:
            decision = RouteDecision.model_validate(decide(state))
            choice = decision.next_agent
            if choice in visited:
                choice = "finish"
        return {"next_agent": choice, "route_history": [*state.get("route_history", []), choice]}

    def researcher(state: TeamState) -> TeamState:
        evidence = buscar_documentacion.invoke({"consulta": state["question"]})
        response = compose("investigador", state["question"], evidence)
        return {"research_output": response, "visited": [*state.get("visited", []), "researcher"]}

    def analyst(state: TeamState) -> TeamState:
        numbers = re.findall(r"(?<!\w)-?\d+(?:[.,]\d+)?", state["question"])
        if len(numbers) >= 2:
            evidence = calcular_variacion.invoke(
                {
                    "valor_inicial": numbers[0].replace(",", "."),
                    "valor_final": numbers[1].replace(",", "."),
                }
            )
        else:
            evidence = "Faltan dos valores numéricos para calcular una variación."
        response = compose("analista", state["question"], evidence)
        return {"analysis_output": response, "visited": [*state.get("visited", []), "analyst"]}

    def finish(state: TeamState) -> TeamState:
        evidence = "\n".join(
            filter(None, [state.get("research_output"), state.get("analysis_output")])
        )
        answer = (
            compose("coordinador", state["question"], evidence)
            if evidence
            else "No hay evidencia suficiente para responder."
        )
        return {
            "answer": answer,
            "messages": [*state.get("messages", []), AIMessage(content=answer)],
            "task_completed": True,
        }

    builder = StateGraph(TeamState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("researcher", researcher)
    builder.add_node("analyst", analyst)
    builder.add_node("finish", finish)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        lambda s: s["next_agent"],
        {
            "researcher": "researcher",
            "analyst": "analyst",
            "finish": "finish",
        },
    )
    builder.add_edge("researcher", "supervisor")
    builder.add_edge("analyst", "supervisor")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=checkpointer)


def run(question: str, *, graph=None) -> TeamState:
    if not question.strip():
        raise ValueError("La pregunta no puede estar vacía")
    selected = graph if graph is not None else build_graph()
    return selected.invoke(
        {
            "question": question,
            "messages": [HumanMessage(content=question)],
            "visited": [],
            "route_history": [],
            "task_completed": False,
        },
        config={"recursion_limit": 12},
    )
