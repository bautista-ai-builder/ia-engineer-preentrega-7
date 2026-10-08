"""Herramientas locales, deterministas y sin acceso a datos externos."""

import re
from decimal import Decimal
from pathlib import Path

from langchain_core.tools import tool

DATA = Path(__file__).resolve().parent / "data"


@tool
def buscar_documentacion(consulta: str) -> str:
    """Busca pasajes relevantes en los documentos técnicos locales."""
    terms = set(re.findall(r"\w{4,}", consulta.lower()))
    ranked = []
    for path in sorted(DATA.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        score = sum(term in content.lower() for term in terms)
        ranked.append((score, path.name, content))
    matches = sorted(ranked, reverse=True)[:2]
    if not matches or matches[0][0] == 0:
        return "No hay evidencia documental relevante."
    return "\n\n".join(f"Fuente: {name}\n{content}" for score, name, content in matches if score)


@tool
def calcular_variacion(valor_inicial: str, valor_final: str) -> str:
    """Calcula diferencia absoluta y variación porcentual entre dos valores."""
    initial, final = Decimal(valor_inicial), Decimal(valor_final)
    difference = final - initial
    percentage = None if initial == 0 else difference / initial * 100
    return f"Diferencia: {difference}; variación porcentual: " + (
        "indefinida (base cero)" if percentage is None else f"{percentage:.2f}%"
    )
