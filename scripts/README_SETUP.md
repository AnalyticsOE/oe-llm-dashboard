# Configuración del Update Automático

El dashboard se actualiza **cada lunes a las 9:00 AM Colombia (UTC-5)** vía GitHub Actions.

---

## Secrets requeridos en GitHub

Ve a `github.com/AnalyticsOE/oe-llm-dashboard` → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Descripción |
|--------|-------------|
| `GH_PAT` | Personal Access Token con permisos `Contents: Read & Write` — ya configurado |
| `GA4_SERVICE_ACCOUNT_JSON` | JSON completo de la cuenta de servicio de Google Cloud |
| `OE_MCP_BASE_URL` | URL base del oe-marketing-mcp (ej: `https://mcp.openenglish.com/api`) |
| `OE_MCP_TOKEN` | Bearer token de autenticación del oe-marketing-mcp |

---

## Cómo obtener `GA4_SERVICE_ACCOUNT_JSON`

1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Selecciona el proyecto de Open English
3. IAM & Admin → **Service Accounts** → Crear cuenta de servicio
   - Nombre: `dashboard-updater`
   - Rol: ninguno (se agrega después)
4. En la cuenta creada → **Keys → Add Key → JSON** → descarga el archivo
5. En GA4 (analytics.google.com) → Propiedad LATAM (283620827) → Admin → **Access Management** → agregar el email de la service account con rol **Viewer**
6. Repetir para la propiedad Brazil (321847880)
7. Copia el contenido completo del JSON descargado como valor del secret `GA4_SERVICE_ACCOUNT_JSON`

---

## Cómo obtener `OE_MCP_BASE_URL` y `OE_MCP_TOKEN`

Estos los provee el equipo de IT / Tecnología de Open English.

El script espera que el endpoint funcione así:
```
POST {OE_MCP_BASE_URL}/GrossSalesDynamic
Authorization: Bearer {OE_MCP_TOKEN}
Content-Type: application/json

{ "CountryGroup": "LATAM", "Type": "SEO", ... }
```

Si el endpoint tiene una estructura diferente, edita la función `mcp_query()` en `scripts/update_dashboard.py`.

---

## Trigger manual

Puedes ejecutar el update manualmente en cualquier momento:

1. Ve a `github.com/AnalyticsOE/oe-llm-dashboard` → **Actions**
2. Selecciona **Weekly Dashboard Update**
3. **Run workflow** → opcionalmente especifica fechas de inicio/fin

---

## Ver los logs

Actions → Weekly Dashboard Update → click en el run más reciente → job `update`
