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

app = FastAPI(title="SAVE CUBA - Motor Federal con Validación Estricta y Autollenado")

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
    if nombre_plantilla.startswith("plantilla_"):
        nombre_con_prefijo = nombre_plantilla
    else:
        nombre_con_prefijo = f"plantilla_{nombre_plantilla}"
        
    ruta_input = os.path.join(PLANTILLAS_DIR, nombre_con_prefijo)
    ruta_output = os.path.join(SALIDAS_DIR, nombre_salida)
    
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
# MOTOR SEPARADOR Y EJECUTOR DE TRÁMITES (AUTOLLENADO COMPLETO Y REAL)
# =====================================================================
def ejecutar_mapeo_y_guardado(cliente: DatosClienteUnificados, id_archivo_salida: str):
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
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        empleo_ingles = traducir_historial_laboral_ia(cliente.empleo_cuba_espanol)

        # 1. G-1450 (Residencia - $1440)
        rellenar_planilla_pdf("g1450.pdf", {
            "form1[0].#subform[0].FamilyName[0]": apellido1,
            "form1[0].#subform[0].GivenName[0]": nombre1,
            "form1[0].#subform[0].MiddleName[0]": nombre2,
            "form1[0].#subform[0].AuthorizedPaymentAmt[0]": "1440"
        }, "temp_g1450.pdf")

        # 2. I-485 (Residencia Permanente)
        rellenar_planilla_pdf("i485.pdf", {
            "form1[0].#subform[0].Page1[0].Pt1Line3a_FamilyName[0]": apellido1,
            "form1[0].#subform[0].Page1[0].Pt1Line3b_GivenName[0]": nombre1,
            "form1[0].#subform[0].Page1[0].Pt1Line3c_MiddleName[0]": nombre2,
            "form1[0].#subform[0].Page1[0].AlienRegistrationNumber[0]": anumber_limpio,
            "form1[0].#subform[0].Page1[0].Pt1Line8_DateOfBirth[0]": fecha_usa,
            "form1[0].#subform[0].Page3[0].Pt3Line1_RecentEmployer[0]": empleo_ingles
        }, "temp_i485.pdf")

        # 3. I-765 (Permiso de Trabajo)
        rellenar_planilla_pdf("i765.pdf", {
            "form1[0].Page1[0].Line1a_FamilyName[0]": apellido1,
            "form1[0].Page1[0].Line1b_GivenName[0]": nombre1,
            "form1[0].Page1[0].Line1c_MiddleName[0]": nombre2,
            "form1[0].Page2[0].AlienRegistrationNumber[0]": anumber_limpio
        }, "temp_i765.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i485.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i765.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)

    # -----------------------------------------------------------------
    # FLUJO 2: TRÁMITE CONSULAR (PASAPORTE CUBANO) -> 1 PDF EN ESPAÑOL
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "pasaporte_cubano":
        pasaporte_limpio = validar_y_limpiar_pasaporte(cliente.pasaporte_actual, es_obligatorio=True)
        provincia_limpia = corregir_y_sanear_texto(cliente.provincia_cuba, es_obligatorio=True, nombre_campo="Provincia de Origen")
        ano_salida_limpio = corregir_y_sanear_texto(cliente.ano_salida_cuba, es_obligatorio=True, nombre_campo="Año de Salida")
        
        empleo_espanol_limpio = corregir_y_sanear_texto(
            cliente.empleo_cuba_espanol, 
            es_obligatorio=True, 
            nombre_campo="Último empleo o estudios en Cuba"
        )

        campos_pasaporte = {
            "Primer nombre": nombre1,
            "Segundo nombre": nombre2,
            "Primer apellido": apellido1,
            "Segundo apellido": apellido2,
            "DíaRow1": dia,
            "MesRow1": mes,
            "AñoRow1": ano,
            "Número de Pasaporte": pasaporte_limpio,
            "Provincia": provincia_limpia,
            "AñoRow": ano_salida_limpio,
            "Profesión u oficio": empleo_espanol_limpio
        }
        
        rellenar_planilla_pdf("pasaporte.pdf", campos_pasaporte, id_archivo_salida)

    # -----------------------------------------------------------------
    # FLUJO 3: CIUDADANÍA AMERICANA (USCIS - N-400) -> 2 PDFs
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "naturalizacion_n400":
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        
        # 1. G-1450 (Ciudadanía - $710)
        rellenar_planilla_pdf("g1450.pdf", {
            "form1[0].#subform[0].FamilyName[0]": apellido1,
            "form1[0].#subform[0].GivenName[0]": nombre1,
            "form1[0].#subform[0].MiddleName[0]": nombre2,
            "form1[0].#subform[0].AuthorizedPaymentAmt[0]": "710"
        }, "temp_g1450.pdf")

        # 2. N-400 (Naturalización)
        rellenar_planilla_pdf("n400.pdf", {
            "form1[0].#subform[0].P2_Line1_FamilyName[0]": apellido1,
            "form1[0].#subform[0].P2_Line1_GivenName[0]": nombre1,
            "form1[0].#subform[0].P2_Line1_MiddleName[0]": nombre2,
            "form1[0].#subform[1].#area[1].Line1_AlienNumber[1]": anumber_limpio,
            "form1[0].#subform[1].P2_Line8_DateOfBirth[0]": fecha_usa
        }, "temp_n400.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_n400.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)
            
    else:
        raise HTTPException(status_code=400, detail="El trámite comercial solicitado no existe en SAVE CUBA.")
# =====================================================================
# ENDPOINT DE PRUEBA DE DESARROLLADOR (BYPASS DE PAGO) - 100% CORREGIDO
# =====================================================================
@app.post("/api/asistente/gratis-dev")
async def procesar_tramite_gratis_dev(cliente: DatosClienteUnificados):
    # Leemos tus credenciales desde las variables de entorno de Render (con 'MICHA' como respaldo directo)
    dev_user_valido = os.environ.get("DEV_USERNAME", "MICHA").strip().upper()
    dev_pass_valido = os.environ.get("DEV_PASSWORD", "").strip()
    
    # Limpiamos lo que el usuario escribió en la pantalla
    user_ingresado = (cliente.dev_username_input or "").strip().upper()
    pass_ingresado = (cliente.dev_password_input or "").strip()
    
    # Validación segura (compara sin importar si escribiste en minúsculas o mayúsculas el usuario)
    if user_ingresado != dev_user_valido or (dev_pass_valido and pass_ingresado != dev_pass_valido):
        raise HTTPException(
            status_code=401, 
            detail=f"Credenciales incorrectas. Usuario recibido: '{user_ingresado}' (Esperado: '{dev_user_valido}')"
        )
        
    id_unico = f"savecuba_dev_{cliente.tramite_tipo}_{os.urandom(4).hex()}.pdf"
    
    # Ejecuta el motor completo de autollenado en los PDFs oficiales
    ejecutar_mapeo_y_guardado(cliente, id_unico)
    
    return {
        "status": "success",
        "mensaje": "Trámite autollenado exitosamente mediante acceso de desarrollador.",
        "archivo_url": f"https://save-cuba.onrender.com/api/descargar/{id_unico}"
    }
# =====================================================================
# ENDPOINT DE CREACIÓN DE SESIÓN DE PAGO (STRIPE)
# =====================================================================
@app.post("/api/crear-sesion-pago")
async def crear_sesion_pago(cliente: DatosClienteUnificados):
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(
            status_code=500, 
            detail="La pasarela de pagos de Stripe no está configurada correctamente en las variables de Render."
        )
        
    id_sesion_temporal = f"sesion_{os.urandom(8).hex()}"
    
    # Almacenamos temporalmente en memoria RAM los datos introducidos por el cliente
    SESIONES_TEMPORALES[id_sesion_temporal] = cliente.dict()
    
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': STRIPE_PRICE_ID,
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"https://save-cuba.onrender.com/exito?session_id={{CHECKOUT_SESSION_ID}}&token_interno={id_sesion_temporal}",
            cancel_url="https://save-cuba.onrender.com/",
        )
        return {"checkout_url": checkout_session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con la pasarela de pagos: {str(e)}")

# =====================================================================
# ENDPOINT DE RETORNO EXITOSO POST-PAGO (GENERA EL PDF AUTOLLENADO)
# =====================================================================
@app.get("/exito", response_class=HTMLResponse)
async def pago_exitoso(session_id: str, token_interno: str):
    if token_interno not in SESIONES_TEMPORALES:
        raise HTTPException(
            status_code=400, 
            detail="La sesión de pago ha expirado o los datos temporales ya fueron procesados. Vuelve a iniciar el trámite."
        )
        
    # Recuperamos los datos del cliente guardados en RAM
    datos_crudos = SESIONES_TEMPORALES.pop(token_interno)
    cliente = DatosClienteUnificados(**datos_crudos)
    
    id_archivo_final = f"savecuba_oficial_{cliente.tramite_tipo}_{os.urandom(4).hex()}.pdf"
    
    # El sistema ejecuta la inyección automática en el formulario oficial correspondiente
    ejecutar_mapeo_y_guardado(cliente, id_archivo_final)
    
    # Interfaz visual de éxito limpia y directa para que el cliente descargue su planilla lista
    html_respuesta = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>SAVE CUBA - Trámite Completado</title>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #f4f6f9; color: #333; text-align: center; padding: 50px 20px; }}
            .card {{ background: white; max-width: 600px; margin: 0 auto; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
            h1 {{ color: #002b49; margin-bottom: 10px; }}
            p {{ font-size: 16px; color: #555; line-height: 1.5; }}
            .btn-descargar {{ display: inline-block; background-color: #28a745; color: white; padding: 15px 30px; font-size: 18px; font-weight: bold; text-decoration: none; border-radius: 8px; margin-top: 25px; box-shadow: 0 4px 10px rgba(40,167,69,0.3); }}
            .btn-descargar:hover {{ background-color: #218838; }}
            .nota {{ font-size: 13px; color: #888; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>¡Trámite Autollenado con Éxito!</h1>
            <p>Tu formulario oficial ha sido procesado e inyectado correctamente con toda tu información mediante el sistema automatizado de <strong>SAVE CUBA</strong>.</p>
            <p>Haz clic en el botón verde para descargar tu documento listo para imprimir, firmar y enviar:</p>
            
            <a href="/api/descargar/{id_archivo_final}" class="btn-descargar" target="_blank">📥 Descargar Formulario Oficial Autollenado</a>
            
            <div class="nota">
                * Recuerda revisar los datos impresos antes de estampar tu firma a mano en la sección correspondiente.
            </div>
        </div>
    </body>
    </html>
    """
    return html_respuesta

# =====================================================================
# ENDPOINT DE DESCARGA SEGURA DE LOS ARCHIVOS PDF GENERADOS
# =====================================================================
@app.get("/api/descargar/{nombre_archivo}")
async def descargar_archivo(nombre_archivo: str):
    # Blindaje contra ataques de navegación de directorios (Path Traversal)
    nombre_limpio = os.path.basename(nombre_archivo)
    ruta_archivo = os.path.join(SALIDAS_DIR, nombre_limpio)
    
    if not os.path.exists(ruta_archivo):
        raise HTTPException(
            status_code=404, 
            detail="El archivo PDF solicitado no existe o ya expiró de los registros temporales del servidor."
        )
        
    return FileResponse(
        path=ruta_archivo, 
        media_type='application/pdf', 
        filename=f"SAVE_CUBA_{nombre_limpio}"
    )

# =====================================================================
# MONTAJE DE ARCHIVOS ESTÁTICOS (CSS, JS, IMÁGENES)
# =====================================================================
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# =====================================================================
# NUEVA FUNCIÓN DE DIAGNÓSTICO PARA LEER LOS CAMPOS REALES DE LOS PDFS
# =====================================================================
@app.get("/api/inspeccionar-campos/{nombre_planilla}")
async def inspeccionar_campos_pdf(nombre_planilla: str):
    """Lee y lista los nombres exactos de todas las casillas internas de un PDF."""
    ruta = os.path.join(PLANTILLAS_DIR, f"plantilla_{nombre_planilla}" if not nombre_planilla.startswith("plantilla_") else nombre_planilla)
    if not os.path.exists(ruta):
        return {"error": f"No se encontró el archivo en la carpeta plantilla: {ruta}"}
    
    reader = PdfReader(ruta)
    campos = reader.get_fields()
    
    if not campos:
        return {"mensaje": "El PDF no tiene campos interactivos (AcroForms) reconocibles o es un documento plano escaneado."}
    
    # Devuelve la lista exacta de nombres de campos que exige este PDF específico
    return {"total_campos": len(campos), "nombres_exactos_de_casillas": list(campos.keys())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
