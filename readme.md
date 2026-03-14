# bot_gastos

Bot personal de Telegram para registrar gastos diarios con mínima fricción. Organiza por categorías configurables, maneja cuotas automáticamente y genera reportes desde Google Sheets.

---

## Requisitos

- Debian/Ubuntu LXC o VM
- Python 3.10+
- Bot de Telegram creado con [@BotFather](https://t.me/BotFather)
- Google Cloud project con **Sheets API** y **Drive API** activadas
- Service Account con acceso a la Google Sheet

---

## Instalación

### 1. Preparar el sistema

```bash
apt update && apt install -y python3 python3-pip python3-venv
mkdir /root/bot_gastos && cd /root/bot_gastos
```

### 2. Copiar los archivos

Copiá `bot.py`, `requirements.txt`, `.env.example` y `bot_gastos.service` a `/root/bot_gastos/`.

### 3. Crear el entorno virtual e instalar dependencias

```bash
python3 -m venv venv
./venv/bin/pip install -U pip wheel
./venv/bin/pip install -r requirements.txt
```

### 4. Configurar el .env

```bash
cp .env.example .env
nano .env
```

Completá los 4 valores:

```env
TELEGRAM_BOT_TOKEN="tu_token_aqui"
TELEGRAM_CHAT_ID="tu_chat_id_aqui"
GOOGLE_CREDENTIALS_PATH="/root/bot_gastos/credentials.json"
GOOGLE_SHEET_ID="id_de_tu_planilla_aqui"
```

---

## Obtener credenciales

### Token de Telegram

1. Abrí [@BotFather](https://t.me/BotFather) en Telegram
2. Escribí `/newbot` y seguí los pasos
3. BotFather te entrega el token — copialo al `.env`

### Chat ID de Telegram

1. Mandá cualquier mensaje a tu bot
2. Abrí en el navegador:
```
https://api.telegram.org/botTU_TOKEN/getUpdates
```
3. Buscá `"chat": {"id": ESTE_NUMERO}` — ese es tu `TELEGRAM_CHAT_ID`

### Google Sheet ID

Está en la URL de la planilla:
```
https://docs.google.com/spreadsheets/d/ESTE_ES_EL_ID/edit
```

### Service Account (credentials.json)

1. Entrá a [console.cloud.google.com](https://console.cloud.google.com)
2. **IAM & Admin → Service Accounts → Create Service Account** → nombre: `bot_gastos` → Create
3. Hacé clic en la service account → **Keys → Add Key → Create new key → JSON**
4. Descargá el archivo y guardalo como `/root/bot_gastos/credentials.json`
5. Abrí el JSON, copiá el campo `client_email`
6. Abrí la planilla → **Compartir** → pegá el `client_email` → rol **Editor** → Enviar

---

## Probar antes de activar el servicio

```bash
cd /root/bot_gastos
./venv/bin/python bot.py
```

Si aparece `Bot iniciado...` sin errores, mandá `1500 café` al bot en Telegram. Deberías ver el mensaje de confirmación con botones. Confirmá y verificá que se escribió una fila en la planilla.

---

## Activar como servicio systemd

```bash
cp bot_gastos.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now bot_gastos
systemctl status bot_gastos
```

El bot va a arrancar automáticamente con el sistema.

---

## Uso

### Registrar un gasto

| Formato | Ejemplo | Comportamiento |
|---|---|---|
| `monto concepto` | `1500 café` | Detecta categoría por concepto |
| `monto Nc concepto` | `60000 6c zapatillas` | 6 cuotas desde este mes → categoría Deudas/Cuotas |
| `monto Nc+Xm concepto` | `60000 6c+1m zapatillas` | 6 cuotas empezando el mes que viene |

El bot siempre pide confirmación antes de guardar. En la confirmación podés cambiar la categoría con el botón **📂 Cambiar categoría**.

### Comandos

| Comando | Descripción |
|---|---|
| `/hoy` | Gastos del día desglosados por ítem |
| `/mes` | Resumen del mes por categoría, ordenado por monto |
| `/cuotas` | Cuotas pendientes en los próximos 6 meses |
| `/categorias` | Lista todas las categorías con keywords |
| `/ayuda` | Todos los comandos disponibles |

### Editar categorías

| Comando | Ejemplo | Descripción |
|---|---|---|
| `/addcategoria` | `/addcategoria Hogar netflix` | Agrega keyword a una categoría |
| `/delcategoria` | `/delcategoria Hogar netflix` | Elimina keyword de una categoría |
| `/addcat` | `/addcat Suscripciones` | Crea una categoría nueva |
| `/delcat` | `/delcat Suscripciones` | Elimina una categoría entera |

---

## Compartir con otro usuario

Por defecto el bot responde solo al `TELEGRAM_CHAT_ID` configurado. Para agregar más usuarios:

**1.** Editá el `.env` con los Chat IDs separados por coma:
```env
TELEGRAM_CHAT_ID="154645571,987654321"
```

**2.** Cambiá la función `is_authorized` en `bot.py`:
```python
def is_authorized(update: Update) -> bool:
    allowed = [int(x.strip()) for x in os.getenv("TELEGRAM_CHAT_ID", "").split(",")]
    return update.effective_user.id in allowed
```

**3.** Reiniciá el servicio:
```bash
systemctl restart bot_gastos
```

Para obtener el Chat ID del otro usuario, pedile que mande un mensaje al bot y revisá `getUpdates`.

---

## Google Sheets — estructura

El bot crea una hoja por mes con nombre `YYYY-MM`. Columnas:

| Fecha | Categoría | Concepto | Monto | Cuota | Tipo |
|---|---|---|---|---|---|
| 2026-03-14 | Hormiga | café | 1500 | | real |
| 2026-03-14 | Deudas/Cuotas | zapatillas | 60000 | 1/6 | real |
| 2026-04-14 | Deudas/Cuotas | zapatillas | 60000 | 2/6 | informativo |

Los gastos `informativo` son cuotas futuras — no suman al total de `/mes` para evitar doble contabilidad.

---

## Categorías por defecto

| Categoría | Keywords |
|---|---|
| Hogar | alquiler, expensas, luz, gas, agua, internet, supermercado |
| Personales | ropa, salud, gimnasio, higiene, ocio, electronica, monitor, notebook, celular, tablet |
| Hormiga | café, transporte, kiosco, delivery, uber, taxi |
| Mascotas | alimento, baño, veterinaria, accesorios |
| Hijos | colegio, club, útiles, actividades |
| Deudas/Cuotas | tarjeta, crédito personal |

Reglas automáticas:
- Gasto con cuotas (`Nc`) → siempre **Deudas/Cuotas**
- Sin match de keyword → **Hormiga** por defecto
- Cambiable en la confirmación con el botón 📂

---

## Logs y estado

```bash
systemctl status bot_gastos
journalctl -u bot_gastos -n 50 --no-pager
journalctl -u bot_gastos -f
```

---

## Troubleshooting

| Síntoma | Causa | Solución |
|---|---|---|
| `InvalidToken` | Token incorrecto o revocado | Regenerar en BotFather y actualizar `.env` |
| `PermissionError` en Sheets | Service Account sin acceso | Compartir la planilla con el `client_email` |
| `Failed to load environment files` | `.env` no existe | `cp .env.example .env` y completar valores |
| `ModuleNotFoundError` | Dependencias no instaladas | `./venv/bin/pip install -r requirements.txt` |
| Bot no responde | Token o Chat ID incorrecto | Verificar variables en `.env` |
| `KeyError: 'pending'` | Botón de sesión anterior | Ignorar — mandar un gasto nuevo |
| systemd status = failed | Ver logs | `journalctl -u bot_gastos -n 20` |

---

## Seguridad

- El bot responde **solo a los Chat IDs configurados**
- `.env` y `credentials.json` con permisos restringidos: `chmod 600 .env credentials.json`
- Service Account con acceso **solo a la planilla necesaria**

---

## Archivos del proyecto

| Archivo | Descripción |
|---|---|
| `bot.py` | Lógica principal del bot |
| `requirements.txt` | Dependencias Python |
| `.env.example` | Template de variables de entorno |
| `bot_gastos.service` | Definición del servicio systemd |
| `config.json` | Categorías personalizadas (se crea automáticamente) |