# Pre-entrega 7: API de producción y monitoreo activo

API FastAPI del orquestador de la pre-entrega 6. Cada petición usa un `thread_id` estable y un checkpoint de LangGraph en Redis. Las solicitudes marcadas para revisión o con verbos sensibles se detienen con `interrupt()`; `/approve` reanuda el mismo thread con `Command(resume=...)`. La API expone salud, disponibilidad y métricas Prometheus.

## Arranque local

Requiere Docker Compose y una clave OpenAI. Copiar `.env.example` a `.env`, completar `OPENAI_API_KEY` y sustituir `API_TOKEN` por un secreto propio.

```bash
docker compose up --build
curl http://localhost:8000/health
curl -H "X-API-Key: TU_TOKEN" -H "Content-Type: application/json" \
  -d '{"thread_id":"demo-1","message":"¿Qué base guarda los pedidos?"}' \
  http://localhost:8000/chat
```

Para una solicitud pendiente, enviar `POST /approve` con `{"thread_id":"demo-1","approved":true}` y el mismo encabezado. `false` rechaza la ejecución. `GET /metrics` exige token y devuelve contadores y latencias; `GET /ready` verifica Redis. La documentación interactiva está en `/docs`.

## Estructura y límites

- `app/graph.py`, `app/tools.py`, `app/data/`: supervisor y especialistas independientes, basados en la pre-entrega 6.
- `app/workflow.py`: compuerta humana y estado del servicio.
- `app/api.py`: autenticación con token, endpoints, errores y métricas.
- `Dockerfile`, `docker-compose.yml`: API y Redis Stack con volumen persistente.

Las acciones sensibles de este prototipo consisten en responder/analizar; **no ejecutan escrituras externas**. La lista de verbos exige revisión, y el cliente también puede fijar `require_approval`. Para producción real se deben añadir identidad de revisores, control de acceso por usuario, límites de solicitudes, trazas centralizadas y un flujo de acciones auditado. Los tests usan `InMemorySaver` y modelos falsos; no sustituyen una prueba real de Redis/OpenAI.
