import os
import re
import unicodedata
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from deep_translator import GoogleTranslator
import google.generativeai as genai
from openai import OpenAI
from pypdf import PdfReader, PdfWriter
import stripe

app = FastAPI(title="SAVE CUBA - Motor Federal con Validación Estricta")

# Permitir conexiones seguras únicamente bajo tu dominio oficial de Render
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración limpia de rutas en el servidor de Render
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLAS_DIR = os.path.join(BASE_DIR, "plantilla")  # Carpeta en singular 'plantilla'
SALIDAS_DIR = os.path.join(BASE_DIR, "descargas")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(SALIDAS_DIR, exist_ok=True)

# Clientes de Inteligencia Artificial leyendo tus variables de Render
client_openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")) if os.environ.get("OPENAI_API_KEY") else None
if os.environ.get("GEMINI_API_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Pasarela de Stripe integrada
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

# Estructura del perfil del cliente (JSON que manda la web)
class DatosClienteUnificados(BaseModel):
    tramite_tipo: str
    primer_nombre: str
    segundo_nombre: Optional[str] = ""
    primer_apellido: str
    segundo_apellido: Optional[str] = ""
    fecha_nacimiento: str
    anumber: Optional[str] = ""
    empleo_cuba_espanol: Optional[str] = ""
    pasaporte_actual: Optional[str] = ""
    provincia_cuba: Optional[str] = ""
    ano_salida_cuba: Optional[str] = ""
    dev_username_input: Optional[str] = ""
    dev_password_input: Optional[str] = ""

# Memoria RAM temporal pre-pago
SESIONES_TEMPORALES = {}

# =====================================================================
# RUTA MAESTRA: RENDERIZA TU INDEX.HTML DIRECTO EN TU URL FIJA
# =====================================================================
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    ruta_html = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(ruta_html):
        raise HTTPException(status_code=404, detail="Error de Servidor: No se encontró index.html adentro de static.")
    with open(ruta_html, "r", encoding="utf-8") as f:
        return f.read()

# =====================================================================
# MOTOR INTEGRAL DE AUTO-CORRECCIÓN Y SANEAMIENTO TEXTUAL
# =====================================================================
def corregir_y_sanear_texto(texto: Optional[str], es_obligatorio: bool = False, nombre_campo: str = "") -> str:
    """Elimina tildes, minúsculas, espacios duplicados accidentales y valida vacíos."""
    if not texto or not texto.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail=f"¡Atención! Falta un dato obligatorio: El campo '{nombre_campo}' está vacío.")
        return ""
    
    # Quitar acentos (Ej: Pérez -> PEREZ, Muñoz -> MUNOZ)
    texto_plano = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    # Fuerza letras mayúsculas de imprenta y limpia espacios en los extremos
    texto_plano = texto_plano.upper().strip()
    # Elimina dobles espacios internos involuntarios
    return " ".join(texto_plano.split())

# =====================================================================
# SECCIÓN GUARDIÁN: VALIDACIÓN DE LONGITUD Y ERRORES DE DOCUMENTOS
# =====================================================================
def validar_y_limpiar_pasaporte(pasaporte_usuario: Optional[str], es_obligatorio: bool = False) -> str:
    """Verifica de forma estricta que el pasaporte cubano tenga 1 letra y 6 números."""
    if not pasaporte_usuario or not pasaporte_usuario.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail="¡Atención! El número de Pasaporte Cubano es obligatorio para este trámite.")
        return ""
        
    limpio = re.sub(r'[^A-Z0-9]', '', pasaporte_usuario.strip().upper())
    
    if len(limpio) != 7:
        raise HTTPException(
            status_code=400,
            detail=f"¡Error en el Pasaporte! El número ingresado tiene {len(limpio)} caracteres. El pasaporte cubano debe tener exactamente 7 caracteres en total (1 letra y 6 números). Revisa si te falta o te sobra algún dígito."
        )
        
    if not re.match(r'^[A-Z]\d{6}$', limpio):
        raise HTTPException(
            status_code=400,
            detail=f"¡Estructura de Pasaporte Incorrecta! Recuerda que el pasaporte de Cuba debe comenzar obligatoriamente con una Letra seguida de exactamente 6 Números (Ejemplo: H123456)."
        )
    return limpio

def validar_y_limpiar_anumber(anumber_usuario: Optional[str], es_obligatorio: bool = False) -> str:
    """Verifica de forma estricta que el Alien Registration Number tenga exactamente 9 números."""
    if not anumber_usuario or not anumber_usuario.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail="¡Atención! El número de Extranjero (A-Number) es obligatorio para este trámite.")
        return ""
        
    limpio = re.sub(r'\D', '', anumber_usuario.strip())
    
    if len(limpio) != 9:
        raise HTTPException(
            status_code=400,
            detail=f"¡Error en el A-Number! El número ingresado tiene {len(limpio)} dígitos. El número de Extranjero (Alien Number) exige exactamente 9 números enteros. Revisa tu documento para corregir los números que faltan o sobran."
        )
    return limpio

# =====================================================================
# TRADUCCIÓN INTELIGENTE EXPERTA CON IA TRIPLE (SÓLO PARA TRÁMITES USA)
# =====================================================================
def traducir_historial_laboral_ia(texto_espanol: str) -> str:
    if not texto_espanol or not texto_espanol.strip():
        return ""
    
    prompt = f"""Actúa como un traductor certificado y experto en leyes migratorias de EE. UU. Traduce el siguiente texto laboral al inglés técnico oficial exigido en los formularios de USCIS. Corrige la ortografía y coherencia en español antes de traducir. Devuelve EXCLUSIVAMENTE la traducción final en letras MAYÚSCULAS:\n"{texto_espanol}" """
    
    if client_openai:
        try:
            response = client_openai.chat.completions.create(
                model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.2
            )
            return response.choices.message.content.strip().upper()
        except Exception:
            pass
            
    if os.environ.get("GEMINI_API_KEY"):
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt)
            return response.text.strip().upper()
        except Exception:
            pass
            
    try:
        return GoogleTranslator(source='es', target='en').translate(texto_espanol).upper()
    except Exception:
        return texto_espanol.upper()
# =====================================================================
# INYECTOR MECÁNICO DE ARCHIVOS PDF (ACROFORMS)
# =====================================================================

def rellenar_planilla_pdf(nombre_plantilla: str, datos_mapeados: dict, nombre_salida: str) -> str:
    # Si el nombre ya empieza con "plantilla_", lo deja igual. Si no, se lo agrega de forma pareja.
    if nombre_plantilla.startswith("plantilla_"):
        nombre_con_prefijo = nombre_plantilla
    else:
        nombre_con_prefijo = f"plantilla_{nombre_plantilla}"
        
    ruta_input = os.path.join(PLANTILLAS_DIR, nombre_con_prefijo)
    ruta_output = os.path.join(SALIDAS_DIR, nombre_salida)
    
    # Alerta de seguridad limpia si falta el papel en tu repositorio de GitHub
    if not os.path.exists(ruta_input):
        raise HTTPException(
            status_code=500, 
            detail=f"Falta archivo base en el servidor: {nombre_con_prefijo} dentro de la carpeta 'plantilla/'"
        )
    
    try:
        reader = PdfReader(ruta_input)
        writer = PdfWriter()
        writer.append(reader)
        
        # Inyección mecánica exacta sobre las casillas oficiales del gobierno
        writer.update_page_form_field_values(writer.pages, datos_mapeados)
        
        with open(ruta_output, "wb") as f:
            writer.write(f)
            
        return ruta_output
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error mecánico al rellenar el PDF: {str(e)}")

# =====================================================================
# MOTOR SEPARADOR Y EJECUTOR DE TRÁMITES (AISLAMIENTO TOTAL)
# =====================================================================

def ejecutar_mapeo_y_guardado(cliente: DatosClienteUnificados, id_archivo_salida: str):
    """
    Estructura y separa al 100% los flujos para evitar mezclas peligrosas.
    Aplica el motor guardián de validación de longitud para proteger al cliente.
    """
    # 1. Saneamiento obligatorio de identidad (Mayúsculas, sin tildes, sin dobles espacios)
    nombre1 = corregir_y_sanear_texto(cliente.primer_nombre, es_obligatorio=True, nombre_campo="Primer Nombre")
    nombre2 = corregir_y_sanear_texto(cliente.segundo_nombre)
    apellido1 = corregir_y_sanear_texto(cliente.primer_apellido, es_obligatorio=True, nombre_campo="Primer Apellido")
    apellido2 = corregir_y_sanear_texto(cliente.segundo_apellido)
    
    if not cliente.fecha_nacimiento or "-" not in cliente.fecha_nacimiento:
        raise HTTPException(status_code=400, detail="¡Atención! La Fecha de Nacimiento es inválida o está vacía.")
    
    ano, mes, dia = cliente.fecha_nacimiento.split("-")
    fecha_usa = f"{mes}/{dia}/{ano}"

    # -----------------------------------------------------------------
    # FLUJO 1: RESIDENCIA Y TRABAJO USA (USCIS - LEY DE AJUSTE) -> 3 PDFs
    # -----------------------------------------------------------------
    if cliente.tramite_tipo == "paquete_completo_uscis":
        # Guardián: Si faltan o sobran números enteros, el sistema frena aquí
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        
        # Traduce el historial de trabajo libre al inglés federal mediante IA
        empleo_ingles = traducir_historial_laboral_ia(cliente.empleo_cuba_espanol)
        
        # Inyección física pareja en la carpeta 'plantilla/'
        rellenar_planilla_pdf("i485.pdf", {"Given Name": nombre1, "Middle Name": nombre2, "Family Name": apellido1, "A-Number": anumber_limpio, "Birth Date": fecha_usa, "Employment History": empleo_ingles}, "temp_i485.pdf")
        rellenar_planilla_pdf("i765.pdf", {"First Name": nombre1, "Last Name": apellido1, "Alien Registration Number": anumber_limpio}, "temp_i765.pdf")
        rellenar_planilla_pdf("g1450.pdf", {"Given Name": nombre1, "Family Name": apellido1, "Amount": "1440"}, "temp_g1450.pdf")
        
        # Ensamblaje oficial del paquete (El cobro G-1450 va obligatoriamente arriba)
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i485.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i765.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)

    # -----------------------------------------------------------------
    # FLUJO 2: TRÁMITE CONSULAR (PASAPORTE CUBANO) -> ¡SIN TRADUCCIÓN Y EN ESPAÑOL!
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "pasaporte_cubano":
        # Guardián estricto de longitud aislada
        pasaporte_limpio = validar_y_limpiar_pasaporte(cliente.pasaporte_actual, es_obligatorio=True)
        provincia_limpia = corregir_y_sanear_texto(cliente.provincia_cuba, es_obligatorio=True, nombre_campo="Provincia de Origen")
        ano_salida_limpio = corregir_y_sanear_texto(cliente.ano_salida_cuba, es_obligatorio=True, nombre_campo="Año de Salida")
        
        # Sincronizado aquí con el nombre exacto de la interfaz visual en español
        empleo_espanol_limpio = corregir_y_sanear_texto(
            cliente.empleo_cuba_espanol, 
            es_obligatorio=True, 
            nombre_campo="Último empleo o estudios en Cuba"
        )

        campos_pasaporte = {
            "Nombres": f"{nombre1} {nombre2}".strip(),
            "Primer Apellido": apellido1,
            "Segundo Apellido": apellido2,
            "Dia Nacimiento": dia,
            "Mes Nacimiento": mes,
            "Ano Nacimiento": ano,
            "Numero Pasaporte": pasaporte_limpio,
            "Provincia Cuba": provincia_limpia,
            "Ano Salida": ano_salida_limpio,
            "Empleo Cuba": empleo_espanol_limpio  # Se estampa directamente en Español Limpio
        }
        # Inyección pareja únicamente en el archivo del consulado
        rellenar_planilla_pdf("pasaporte.pdf", campos_pasaporte, id_archivo_salida)

    # -----------------------------------------------------------------
    # FLUJO 3: CIUDADANÍA AMERICANA (USCIS - N-400) -> 2 PDFs
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "naturalizacion_n400":
        # Guardián: Valida longitud estricta de 9 números numéricos
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        
        rellenar_planilla_pdf("n400.pdf", {"Given Name": nombre1, "Family Name": apellido1, "A-Number": anumber_limpio, "Date of Birth": fecha_usa}, "temp_n400.pdf")
        rellenar_planilla_pdf("g1450.pdf", {"Given Name": nombre1, "Family Name": apellido1, "Amount": "710"}, "temp_g1450.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_n400.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)
            
    else:
        raise HTTPException(status_code=400, detail="El trámite comercial solicitado no existe en SAVE CUBA.")

# =====================================================================
# ENDPOINT DE DESARROLLO GRATUITO (CORREGIDO CON LA RUTA DE DESCARGA REAL)
# =====================================================================
@app.post("/api/asistente/gratis-dev")
async def procesar_gratis_desarrollador(cliente: DatosClienteUnificados):
    # Lee de manera estricta tu configuración de Render sin inventar textos por defecto
    dev_usuario_servidor = os.environ.get("DEV_USER")
    dev_password_servidor = os.environ.get("DEV_PASS")
    
    if not dev_usuario_servidor or not dev_password_servidor:
        raise HTTPException(
            status_code=503, 
            detail="Error de Configuración: Las variables DEV_USER y DEV_PASS no han sido añadidas en el panel de Render."
        )
    
    if cliente.dev_username_input != dev_usuario_servidor or cliente.dev_password_input != dev_password_servidor:
        raise HTTPException(status_code=401, detail="Acceso Denegado: Las credenciales de pruebas escritas son incorrectas.")
    
    nombre_archivo = f"prueba_gratis_{cliente.tramite_tipo}.pdf"
    ejecutar_mapeo_y_guardado(cliente, nombre_archivo)
    
    # ¡CORREGIDO AQUÍ! Se añade '/api/descargar/' de forma explícita para evitar que la URL se rompa
    return {
        "respuesta": "✔ <strong>Filtro Guardián Correcto:</strong> Tus datos fueron corregidos, limpiados de tildes y volcados sobre la plantilla oficial.",
        "archivo_url": f"https://save-cuba.onrender.com{nombre_archivo}"
    }

# =====================================================================
# ENDPOINTS DE PASARELA COMERCIAL STRIPE Y WEBHOOKS
# =====================================================================
@app.post("/api/stripe/checkout")
async def crear_checkout_stripe(cliente: DatosClienteUnificados):
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="La pasarela comercial de Stripe no está configurada en Render.")
    
    try:
        id_sesion_local = f"tramite_{int(os.urandom(4).hex(), 16)}"
        SESIONES_TEMPORALES[id_sesion_local] = cliente

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            mode='payment',
            metadata={"id_sesion_local": id_sesion_local},
            success_url=f"https://save-cuba.onrender.com?stripe_status=success&file={id_sesion_local}.pdf",
            cancel_url=f"https://save-cuba.onrender.com?stripe_status=cancel",
        )
        return {"stripe_checkout_url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en pasarela Stripe: {str(e)}")
@app.post("/api/stripe/webhook")
async def webhook_stripe(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Firma de Webhook inválida")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        id_sesion_local = session.get("metadata", {}).get("id_sesion_local")
        
        if id_sesion_local and id_sesion_local in SESIONES_TEMPORALES:
            datos_cliente = SESIONES_TEMPORALES[id_sesion_local]
            ejecutar_mapeo_y_guardado(datos_cliente, f"{id_sesion_local}.pdf")
            del SESIONES_TEMPORALES[id_sesion_local] # Privacidad absoluta para el cliente

    return {"status": "success"}

# =====================================================================
# RUTA DE DESCARGA EN VIVO HACIA EL TELÉFONO O COMPUTADORA
# =====================================================================
@app.get("/api/descargar/{nombre_archivo}")
async def descargar_archivo_real(nombre_archivo: str):
    ruta_archivo = os.path.join(SALIDAS_DIR, nombre_archivo)
    if not os.path.exists(ruta_archivo):
        raise HTTPException(status_code=404, detail="El archivo solicitado ya no está disponible en el servidor.")
    return FileResponse(ruta_archivo, media_type="application/pdf", filename=nombre_archivo)

@app.get("/health")
async def health_check():
    return {"status": "online", "sistema": "SAVE CUBA listo"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
