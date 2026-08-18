import os
import re
import shutil
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from deep_translator import GoogleTranslator
from pypdf import PdfReader, PdfWriter
import google.generativeai as genai
from openai import OpenAI
import stripe

app = FastAPI(title="SAVE CUBA - Motor Federal de Producción")

# Habilitar CORS para conectar de manera segura con tu index.html
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar los clientes de IA leyendo de forma segura las variables de entorno de Render
client_openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "temporal_key")) if os.environ.get("OPENAI_API_KEY") else None
if os.environ.get("GEMINI_API_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Configurar Stripe como opcional para que Render compile sin dar errores en el primer despliegue
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

# Configuración de rutas del servidor
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLAS_DIR = os.path.join(BASE_DIR, "plantillas")
SALIDAS_DIR = os.path.join(BASE_DIR, "descargas")

# Crear directorios automáticamente si no existen
os.makedirs(SALIDAS_DIR, exist_ok=True)

# Almacén temporal en memoria RAM (Privacidad absoluta, se destruye tras generar el PDF)
SESIONES_TEMPORALES = {}

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

# =====================================================================
# MOTOR DE INTELIGENCIA ARTIFICIAL Y TRADUCCIÓN CON RESPALDO TRIPLE
# =====================================================================
def procesar_texto_con_ia_y_respaldo(texto_espanol: str) -> str:
    if not texto_espanol or not texto_espanol.strip():
        return ""

    prompt_instruccion = f"""
    Actúa como un preparador de documentos de inmigración experto en Estados Unidos. 
    Primero, analiza el siguiente texto en español, corrige cualquier error de ortografía, redacción o coherencia. 
    Luego, tradúcelo a un inglés formal, técnico y legal adecuado para los formularios de USCIS (como el I-485 o I-765). 
    Devuelve ÚNICAMENTE la traducción final en inglés, en letras MAYÚSCULAS y sin textos aclaratorios.
    
    Texto a procesar: "{texto_espanol}"
    """

    # --- MOTOR 1: OpenAI ---
    if client_openai:
        try:
            response = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt_instruccion}],
                temperature=0.3
            )
            return response.choices.message.content.strip().upper()
        except Exception as e:
            print(f"SAVE CUBA Alerta: Falló OpenAI, usando Gemini. Motivo: {e}")

    # --- MOTOR 2: Gemini ---
    if os.environ.get("GEMINI_API_KEY"):
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            response = model.generate_content(prompt_instruccion)
            return response.text.strip().upper()
        except Exception as e:
            print(f"SAVE CUBA Alerta: Falló Gemini, usando red de seguridad básica. Motivo: {e}")

    # --- MOTOR 3: Red de seguridad final gratuita ---
    try:
        traduccion_basica = GoogleTranslator(source='es', target='en').translate(texto_espanol)
        return traduccion_basica.strip().upper()
    except Exception as e:
        return texto_espanol.upper() # Retorno de emergencia si todo falla
# =====================================================================
# MOTOR DE RECTIFICACIÓN Y COMPROBACIÓN DE ERRORES AUTOMÁTICA
# =====================================================================

def rectificar_texto_general(texto: Optional[str], es_obligatorio: bool = False, nombre_campo: str = "") -> str:
    if not texto or not texto.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail=f"Error en SAVE CUBA: El campo '{nombre_campo}' está vacío.")
        return ""
    return " ".join(texto.strip().split()).upper()

def rectificar_pasaporte(pasaporte_raw: Optional[str], es_obligatorio: bool = False) -> str:
    if not pasaporte_raw or not pasaporte_raw.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail="Error en SAVE CUBA: El Pasaporte es obligatorio para este trámite.")
        return ""
    limpio = re.sub(r'[^A-Z0-9]', '', pasaporte_raw.strip().upper())
    if not re.match(r'^[A-Z]\d{6}$', limpio):
        raise HTTPException(
            status_code=400, 
            detail=f"Error en SAVE CUBA: Formato de pasaporte '{pasaporte_raw}' inválido. Debe contener exactamente 1 letra y 6 dígitos (Ej: H123456)."
        )
    return limpio

def rectificar_anumber(anumber_raw: Optional[str], es_obligatorio: bool = False) -> str:
    if not anumber_raw or not anumber_raw.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail="Error en SAVE CUBA: El número de Extranjero (A-Number) es obligatorio.")
        return ""
    limpio = re.sub(r'\D', '', anumber_raw.strip())
    if len(limpio) != 9:
        raise HTTPException(
            status_code=400, 
            detail=f"Error en SAVE CUBA: El A-Number '{anumber_raw}' es incorrecto. Debe tener exactamente 9 dígitos numéricos."
        )
    return limpio

# =====================================================================
# INYECTOR REAL DE DATOS SOBRE ACROFORMS (PDF)
# =====================================================================

def rellenar_planilla_pdf(nombre_plantilla: str, datos_mapeados: dict, nombre_salida: str) -> str:
    ruta_input = os.path.join(PLANTILLAS_DIR, nombre_plantilla)
    ruta_output = os.path.join(SALIDAS_DIR, nombre_salida)
    
    if not os.path.exists(ruta_input):
        raise HTTPException(status_code=500, detail=f"Falta archivo base en el servidor: {nombre_plantilla} en la carpeta 'plantillas/'")
    
    try:
        reader = PdfReader(ruta_input)
        writer = PdfWriter()
        writer.append(reader)
        
        # Inyección física en los campos interactivos del PDF gubernamental
        writer.update_page_form_field_values(writer.pages, datos_mapeados)
        
        with open(ruta_output, "wb") as f:
            writer.write(f)
            
        return ruta_output
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al escribir en el PDF {nombre_plantilla}: {str(e)}")

def ejecutar_mapeo_y_guardado(cliente, id_archivo_salida: str):
    """Lógica unificada encargada de mapear los datos traducidos sobre las 5 plantillas reales"""
    nombre1 = rectificar_texto_general(cliente.primer_nombre, es_obligatorio=True, nombre_campo="Primer Nombre")
    nombre2 = rectificar_texto_general(cliente.segundo_nombre)
    apellido1 = rectificar_texto_general(cliente.primer_apellido, es_obligatorio=True, nombre_campo="Primer Apellido")
    apellido2 = rectificar_texto_general(cliente.segundo_apellido)
    provincia = rectificar_texto_general(cliente.provincia_cuba)
    
    pasaporte_rectificado = rectificar_pasaporte(cliente.pasaporte_actual, es_obligatorio=(cliente.tramite_tipo == "pasaporte_cubano"))
    anumber_rectificado = rectificar_anumber(cliente.anumber, es_obligatorio=(cliente.tramite_tipo in ["paquete_completo_uscis", "naturalizacion_n400"]))
    
    ano, mes, dia = cliente.fecha_nacimiento.split("-")
    fecha_formateada_usa = f"{mes}/{dia}/{ano}"
    
    empleo_ingles = procesar_texto_con_ia_y_respaldo(cliente.empleo_cuba_espanol)

    # 1. FLUJO RESIDENCIA Y TRABAJO
    if cliente.tramite_tipo == "paquete_completo_uscis":
        rellenar_planilla_pdf("plantilla_i485.pdf", {"Given Name": nombre1, "Family Name": apellido1, "A-Number": anumber_rectificado, "Birth Date": fecha_formateada_usa, "Employment History": empleo_ingles}, "temp_i485.pdf")
        rellenar_planilla_pdf("plantilla_i765.pdf", {"First Name": nombre1, "Last Name": apellido1, "Alien Registration Number": anumber_rectificado}, "temp_i765.pdf")
        rellenar_planilla_pdf("plantilla_g1450.pdf", {"Given Name": nombre1, "Family Name": apellido1, "Amount": "1440"}, "temp_g1450.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i485.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i765.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)

    # 2. FLUJO PASAPORTE CUBANO
    elif cliente.tramite_tipo == "pasaporte_cubano":
        campos_pasaporte = {
            "Nombres": f"{nombre1} {nombre2}".strip(),
            "Primer Apellido": apellido1,
            "Segundo Apellido": apellido2,
            "Dia Nacimiento": dia,
            "Mes Nacimiento": mes,
            "Ano Nacimiento": ano,
            "Numero Pasaporte": pasaporte_rectificado,
            "Provincia Cuba": provincia,
            "Ano Salida": cliente.ano_salida_cuba
        }
        rellenar_planilla_pdf("plantilla_pasaporte.pdf", campos_pasaporte, id_archivo_salida)

    # 3. FLUJO NATURALIZACIÓN N-400
    elif cliente.tramite_tipo == "naturalizacion_n400":
        rellenar_planilla_pdf("plantilla_n400.pdf", {"Given Name": nombre1, "Family Name": apellido1, "A-Number": anumber_rectificado, "Date of Birth": fecha_formateada_usa}, "temp_n400.pdf")
        rellenar_planilla_pdf("plantilla_g1450.pdf", {"Given Name": nombre1, "Family Name": apellido1, "Amount": "710"}, "temp_g1450.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_n400.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)

# =====================================================================
# ENDPOINT DE PRUEBAS GRATIS (SECRETO: CHECKEA TU DEV_USER Y DEV_PASS)
# =====================================================================
@app.post("/api/asistente/gratis-dev")
async def procesar_gratis_desarrollador(cliente: DatosClienteUnificados):
    dev_usuario_servidor = os.environ.get("DEV_USER", "admin_save")
    dev_password_servidor = os.environ.get("DEV_PASS", "cuba_libre_2026")
    
    if cliente.dev_username_input != dev_usuario_servidor or cliente.dev_password_input != dev_password_servidor:
        raise HTTPException(status_code=401, detail="Credenciales de desarrollo incorrectas. Acceso denegado.")
    
    nombre_archivo = f"prueba_gratis_{cliente.tramite_tipo}.pdf"
    ejecutar_mapeo_y_guardado(cliente, nombre_archivo)
    
    api_url_base = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
    return {"archivo_url": f"{api_url_base}/api/descargar/{nombre_archivo}"}

# =====================================================================
# RUTAS DE COBRO DE STRIPE (DORMIDAS HASTA QUE CONFIGURES TUS LLAVES)
# =====================================================================
@app.post("/api/stripe/checkout")
async def crear_checkout_stripe(cliente: DatosClienteUnificados):
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="El sistema de cobros con Stripe no está configurado aún en Render.")
    
    api_url_base = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
    try:
        id_sesion_local = f"tramite_{int(os.urandom(4).hex(), 16)}"
        SESIONES_TEMPORALES[id_sesion_local] = cliente

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            mode='payment',
            metadata={"id_sesion_local": id_sesion_local},
            success_url=f"{api_url_base}?stripe_status=success&file={id_sesion_local}.pdf",
            cancel_url=f"{api_url_base}?stripe_status=cancel",
        )
        return {"stripe_checkout_url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en Stripe: {str(e)}")

@app.post("/api/stripe/webhook")
async def webhook_stripe(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Firma inválida")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        id_sesion_local = session.get("metadata", {}).get("id_sesion_local")
        
        if id_sesion_local and id_sesion_local in SESIONES_TEMPORALES:
            datos_cliente = SESIONES_TEMPORALES[id_sesion_local]
            ejecutar_mapeo_y_guardado(datos_cliente, f"{id_sesion_local}.pdf")
            del SESIONES_TEMPORALES[id_sesion_local] # Privacidad absoluta

    return {"status": "success"}
# =====================================================================
# RUTA DE DESCARGA EN VIVO (Manda el PDF real a la PC del cliente)
# =====================================================================
@app.get("/api/descargar/{nombre_archivo}")
async def descargar_archivo_real(nombre_archivo: str):
    ruta_archivo = os.path.join(SALIDAS_DIR, nombre_archivo)
    if not os.path.exists(ruta_archivo):
        raise HTTPException(status_code=404, detail="El archivo solicitado ya no está disponible en el servidor.")
    return FileResponse(ruta_archivo, media_type="application/pdf", filename=nombre_archivo)

@app.get("/health")
async def health_check():
    return {"status": "online", "sistema": "SAVE CUBA ready"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
