---
name: orientador-medicamentos
description: Usa el servidor MCP "Orientador de Medicamentos" para orientar (en español o inglés) sobre síntomas, fichas de medicamentos, dosis pediátricas, interacciones, contraindicaciones, triaje de urgencia, farmacovigilancia (API openFDA) y farmacias reales (API OpenStreetMap). Actívala cuando el usuario pregunte por medicamentos, fármacos, dosis, efectos adversos, interacciones, farmacias o si debe ir al médico.
license: MIT
compatibility: opencode
metadata:
  audience: agents
  endpoint: https://orientador-mcp.onrender.com
  protocols: mcp, http-rest
---

# Orientador de Medicamentos — skill para agentes

Skill para que un agente use el servidor MCP del proyecto **`langchain-tool`** sin
reinventar lógica: el servidor expone 10 tools, 6 resources y 3 prompts por HTTP,
**sin autenticación** (sin API key, sin login, con CORS abierto).

## Cuándo usarla

- El usuario pregunta por un medicamento, síntoma, dosis, interacción, contraindicación,
  urgencia/triaje, efectos adversos o farmacias.
- Hace falta orientación general bilingüe (ES/EN) con disclaimer médico.

No usarla para: diagnósticos, recetas, prescribir antibióticos o fármacos con receta.

## Cómo conectar (sin credenciales)

El servidor está en `https://orientador-mcp.onrender.com` (en local: `http://127.0.0.1:8000`).

1. **MCP (recomendado)** — endpoint `POST /mcp` (JSON-RPC del protocolo MCP,
   respuestas JSON planas, `stateless`, sin sesión).
2. **REST** — `POST /chat` con `{"input": "...", "session_id": "opcional", "language": "es|en|auto"}`.
3. **Descubrimiento** — `GET /` (estado), `GET /tools`, `GET /resources`, `GET /prompts`.

Verificación rápida:

```bash
curl -s https://orientador-mcp.onrender.com/ | jq .tools_total   # -> 10
curl -s -X POST https://orientador-mcp.onrender.com/chat \
  -H 'Content-Type: application/json' \
  -d '{"input":"¿Qué es el ibuprofeno?","session_id":"demo"}'
```

Si el servidor está dormido (plan gratuito de Render), la primera petición tarda ~1 min.

## Las 10 tools

| Tool | Tipo | Uso |
|---|---|---|
| `analizar_sintomas` | local | síntomas en texto libre → causas, OTC, alarmas |
| `buscar_medicamento` | local | ficha por nombre comercial o principio activo |
| `calcular_dosis` | local | dosis pediátrica por peso (mg/kg) |
| `verificar_interaccion` | local | interacción entre 2 fármacos |
| `consultar_contraindicacion` | local | fármaco + condición clínica |
| `evaluar_urgencia` | local | triaje: 🟢 autocuidado / 🟡 médico / 🔴 112 |
| `buscar_farmacia` | local | farmacias de muestra (datos simulados) |
| `calcular` | local | aritmética segura (mg, ml, tomas) |
| `consultar_farmacovigilancia` | **API internet #1** | notificaciones de reacciones adversas de **openFDA / FAERS (NIH)** |
| `buscar_farmacia_real` | **API internet #2** | farmacias reales de **OpenStreetMap** (Nominatim + Overpass) |

Las dos tools de API son públicas y **no llevan autenticación**; si la red falla,
devuelven un aviso y sugieren el fallback local (`buscar_farmacia`).

## Prompts MCP (para consumir las APIs de internet)

- `farmacovigilancia_openfda(medicamento)` → redacta la llamada a openFDA.
- `farmacias_reales_osm(ubicacion)` → redacta la llamada a OpenStreetMap.
- `consulta_internet(medicamento, ubicacion)` → encadena ambas APIs.

## Resources MCP (6)

`medicamentos://dataset`, `sintomas://dataset`, `interacciones://dataset`,
`contraindicaciones://dataset`, `farmacias://dataset` (JSON completos) y
`orientador://guia` (catálogo en Markdown de tools/prompts/endpoints).

## Reglas de seguridad que debe respetar el agente

1. Es **orientación general**: nunca diagnóstico ni receta. No pautes antibióticos
   ni medicación con receta.
2. Ante señales de alarma (dolor torácico, dificultad respiratoria, sangrado abundante,
   pérdida de conciencia, hinchazón de lengua/labios, idea suicida) → **112 / urgencias**.
3. Embarazo, lactancia, menores de 2 años o enfermedad crónica: ser conservador y
   remitir a farmacéutico/médico.
4. Termina **siempre** cada respuesta con el disclaimer del idioma:
   - ES: `⚠️ Orientación general, no sustituye al médico o farmacéutico.`
   - EN: `⚠️ General guidance, does not replace your doctor or pharmacist.`
5. Las APIs externas son datos de referencia (FAERS = reportes espontáneos, OSM =
   datos colaborativos): advertir de que pueden estar incompletos o desactualizados.

## Formato de respuesta

Responde en el idioma del usuario (detecta ES/EN), con listas cortas, citando si el
dato viene de una API (`openFDA`, `OpenStreetMap`) o del dataset local.
