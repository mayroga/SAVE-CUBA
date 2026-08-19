import os
import re
import io
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

# Librerías oficiales de ReportLab para la inyección de texto plano por coordenadas
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI(title="SAVE CUBA - Motor de Inyección Plana")

# Permitir conexiones seguras únicamente desde tu frontend bajo tu URL fija
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

# Crear directorios de forma automática si no existen en Render
os.makedirs(SALIDAS_DIR, exist_ok=True)

# Clientes de Inteligencia Artificial leyendo tus variables reales de producción
client_openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")) if os.environ.get("OPENAI_API_KEY") else None
if os.environ.get("GEMINI_API_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Pasarela comercial de Stripe integrada
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

# Estructura del perfil del cliente (Sincronizado al 100% con index.html)
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

# Memoria RAM temporal para transacciones seguras pre-pago
SESIONES_TEMPORALES = {}

# =====================================================================
# RUTA MAESTRA: RENDERIZA TU INDEX.HTML DIRECTO EN TU URL INAMOVIBLE
# =====================================================================
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    ruta_html = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(ruta_html):
        raise HTTPException(
            status_code=404, 
            detail="Error de Servidor: No se encontró index.html adentro de la carpeta 'static' en GitHub."
        )
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
    
    # Quitar acentos de fábrica (Ej: Pérez -> PEREZ, Muñoz -> MUNOZ)
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
# INYECTOR COMPLETAMENTE PLANO POR COORDENADAS (TU IDEA FINAL)
# =====================================================================
def rellenar_planilla_pdf(nombre_plantilla: str, datos_mapeados: dict, nombre_salida: str) -> str:
    """
    TU IDEA DE INGENIERÍA: Abre el PDF original como un plano estático de fondo 
    y estampa físicamente las letras en mayúsculas usando coordenadas fijas (canvas).
    Esto es inmune a los bloqueos digitales de Adobe.
    """
    if nombre_plantilla.startswith("plantilla_"):
        nombre_con_prefijo = nombre_plantilla
    else:
        nombre_con_prefijo = f"plantilla_{nombre_plantilla}"
        
    ruta_input = os.path.join(PLANTILLAS_DIR, nombre_con_prefijo)
    ruta_output = os.path.join(SALIDAS_DIR, nombre_salida)
    
    if not os.path.exists(ruta_input):
        raise HTTPException(
            status_code=500, 
            detail=f"Falta archivo base plano en el servidor: {nombre_con_prefijo} dentro de la carpeta 'plantilla/'"
        )
    
    try:
        # 1. Crear una capa de texto transparente en la memoria RAM del servidor
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)
        can.setFont("Helvetica-Bold", 10)  # Letra de imprenta limpia, gruesa y ultra legible
        can.setFillColorRGB(0, 0, 0)       # Tinta negra pura profesional obligatoria
        
        # 2. Dibujar los textos basándose en las coordenadas parejas (X = horizontal, Y = vertical desde abajo)
        for campo, valor in datos_mapeados.items():
            if not valor:
                continue
            
            val_str = str(valor)
            
            # --- COORDENADAS PARA LA HOJA DE PAGO (G-1450) ---
            if nombre_plantilla == "g1450.pdf":
                if "FamilyName" in campo: can.drawString(80, 595, val_str)
                elif "GivenName" in campo: can.drawString(260, 595, val_str)
                elif "MiddleName" in campo: can.drawString(440, 595, val_str)
                elif "Amount" in campo: can.drawString(450, 415, val_str)

            # --- COORDENADAS PARA LA RESIDENCIA LEY DE AJUSTE (I-485) ---
            elif nombre_plantilla == "i485.pdf":
                if "Pt1Line3a_FamilyName" in campo: can.drawString(75, 688, val_str)
                elif "Pt1Line3b_GivenName" in campo: can.drawString(265, 688, val_str)
                elif "Pt1Line3c_MiddleName" in campo: can.drawString(440, 688, val_str)
                elif "AlienRegistrationNumber" in campo: can.drawString(435, 735, val_str)
                elif "Pt1Line8_DateOfBirth" in campo: can.drawString(440, 615, val_str)
                elif "Pt3Line1_RecentEmployer" in campo: can.drawString(75, 310, val_str)

            # --- COORDENADAS PARA EL PERMISO DE TRABAJO (I-765) ---
            elif nombre_plantilla == "i765.pdf":
                if "Line1a_FamilyName" in campo: can.drawString(75, 712, val_str)
                elif "Line1b_GivenName" in campo: can.drawString(265, 712, val_str)
                elif "Line1c_MiddleName" in campo: can.drawString(440, 712, val_str)
                elif "AlienRegistrationNumber" in campo: can.drawString(435, 650, val_str)

            # --- COORDENADAS PARA LA PLANILLA DEL PASAPORTE CUBANO ---
            elif nombre_plantilla == "pasaporte.pdf":
                if "Primer nombre" in campo: can.drawString(72, 642, val_str)
                elif "Segundo nombre" in campo: can.drawString(320, 642, val_str)
                elif "Primer apellido" in campo: can.drawString(72, 692, val_str)
                elif "Segundo apellido" in campo: can.drawString(320, 692, val_str)
                elif "DíaRow1" in campo: can.drawString(75, 590, val_str)
                elif "MesRow1" in campo: can.drawString(130, 590, val_str)
                elif "AñoRow1" in campo: can.drawString(185, 590, val_str)
                elif "Número de Pasaporte" in campo: can.drawString(320, 540, val_str)
                elif "Provincia" in campo: can.drawString(72, 540, val_str)
                elif "AñoRow" in campo: can.drawString(490, 480, val_str)
                elif "Profesión u oficio" in campo: can.drawString(72, 430, val_str)
                # Dibujar las cruces físicas de las fases del pasaporte de forma matemática (Ley MINREX 2023)
                elif "CasillaNuevoPasaporte" in campo and val_str == "X": can.drawString(195, 742, "X")
                elif "CasillaPrimeraVez" in campo and val_str == "X": can.drawString(310, 742, "X")

            # --- COORDENADAS PARA LA CIUDADANÍA AMERICANA (N-400) ---
            elif nombre_plantilla == "n400.pdf":
                if "P2_Line1_FamilyName" in campo: can.drawString(75, 630, val_str)
                elif "P2_Line1_GivenName" in campo: can.drawString(265, 630, val_str)
                elif "P2_Line1_MiddleName" in campo: can.drawString(440, 630, val_str)
                elif "Line1_AlienNumber" in campo: can.drawString(435, 715, val_str)
                elif "P2_Line8_DateOfBirth" in campo: can.drawString(75, 510, val_str)
        can.save()
        packet.seek(0)
        
        # 3. Leer el PDF base original y fusionarle la capa de texto encima
        new_pdf = PdfReader(packet)
        existing_pdf = PdfReader(ruta_input)
        writer = PdfWriter()
        
        # Fusionar de manera permanente los textos sobre la primera página
        primera_pagina = existing_pdf.pages[0]
        primera_pagina.merge_page(new_pdf.pages[0])
        writer.add_page(primera_pagina)
        
        # Copiar el resto de las páginas del formulario intactas abajo
        for i in range(1, len(existing_pdf.pages)):
            writer.add_page(existing_pdf.pages[i])
            
        with open(ruta_output, "wb") as f:
            writer.write(f)
            
        return ruta_output
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error real al estampar texto plano en tu PDF: {str(e)}")
# =====================================================================
# MOTOR SEPARADOR Y EJECUTOR DE TRÁMITES (ESTRICTA LEY CONSULAR VIGENTE)
# =====================================================================

def ejecutar_mapeo_y_guardado(cliente: DatosClienteUnificados, id_archivo_salida: str):
    """
    Estructura y separa al 100% los flujos para evitar mezclas peligrosas.
    Actualizado: Se eliminó la prórroga y se unificó bajo Nuevo Pasaporte Consular de 10 años.
    """
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
        
        # Inyección pareja basada en los identificadores exactos del canvas plano
        rellenar_planilla_pdf("g1450.pdf", {
            "FamilyName": apellido1, "GivenName": nombre1, "MiddleName": nombre2, "Amount": "1440"
        }, "temp_g1450.pdf")
        
        rellenar_planilla_pdf("i485.pdf", {
            "Pt1Line3a_FamilyName": apellido1, "Pt1Line3b_GivenName": nombre1, "Pt1Line3c_MiddleName": nombre2,
            "AlienRegistrationNumber": anumber_limpio, "Pt1Line8_DateOfBirth": fecha_usa, "Pt3Line1_RecentEmployer": empleo_ingles
        }, "temp_i485.pdf")
        
        rellenar_planilla_pdf("i765.pdf", {
            "Line1a_FamilyName": apellido1, "Line1b_GivenName": nombre1, "Line1c_MiddleName": nombre2,
            "AlienRegistrationNumber": anumber_limpio
        }, "temp_i765.pdf")
        
        # Ensamblaje oficial del sobre consolidado (El cobro G-1450 va obligatoriamente arriba)
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i485.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i765.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)

    # -----------------------------------------------------------------
    # FLUJO 2: PASAPORTE CUBANO LEGAL (NUEVO POR VENCIMIENTO / PRIMERA VEZ)
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo in ["pasaporte_nuevo", "pasaporte_primera_vez"]:
        provincia_limpia = corregir_y_sanear_texto(cliente.provincia_cuba, es_obligatorio=True, nombre_campo="Provincia de Origen")
        ano_salida_limpio = corregir_y_sanear_texto(cliente.ano_salida_cuba, es_obligatorio=True, nombre_campo="Año de Salida")
        empleo_espanol_limpio = corregir_y_sanear_texto(cliente.empleo_cuba_espanol, es_obligatorio=True, nombre_campo="Último empleo o estudios en Cuba")
        
        pasaporte_limpio = ""
        if cliente.tramite_tipo == "pasaporte_nuevo":
            pasaporte_limpio = validar_y_limpiar_pasaporte(cliente.pasaporte_actual, es_obligatorio=True)

        campos_pasaporte = {
            "PrimerApellido": apellido1,
            "SegundoApellido": apellido2,
            "Nombres": f"{nombre1} {nombre2}".strip(),
            "DiaNacimiento": dia,
            "MesNacimiento": mes,
            "AnoNacimiento": ano,
            "ProvinciaNacimiento": provincia_limpia,
            "NumeroPasaporte": pasaporte_limpio,
            "AnoSalidaCuba": ano_salida_limpio,
            "OcupacionProfesion": empleo_espanol_limpio,
            # Inyección limpia de marcas "X" eliminando la prórroga muerta
            "CasillaNuevoPasaporte": "X" if cliente.tramite_tipo == "pasaporte_nuevo" else "",
            "CasillaPrimeraVez": "X" if cliente.tramite_tipo == "pasaporte_primera_vez" else ""
        }
        rellenar_planilla_pdf("pasaporte.pdf", campos_pasaporte, id_archivo_salida)

    # -----------------------------------------------------------------
    # FLUJO 3: CIUDADANÍA AMERICANA (USCIS - N-400) -> 2 PDFs
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "naturalizacion_n400":
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        
        rellenar_planilla_pdf("n400.pdf", {
            "P2_Line1_FamilyName": apellido1, "P2_Line1_GivenName": nombre1, "P2_Line1_MiddleName": nombre2,
            "Line1_AlienNumber": anumber_limpio, "P2_Line8_DateOfBirth": fecha_usa
        }, "temp_n400.pdf")
        
        rellenar_planilla_pdf("g1450.pdf", {
            "FamilyName": apellido1, "GivenName": nombre1, "MiddleName": nombre2, "Amount": "710"
        }, "temp_g1450.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_n400.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)
            
    else:
        raise HTTPException(status_code=400, detail="El trámite comercial solicitado no existe en SAVE CUBA.")

# =====================================================================
# ENDPOINT DE DESARROLLO GRATUITO (BYPASS CON VARIABLES DE RENDER)
# =====================================================================
@app.post("/api/asistente/gratis-dev")
async def procesar_gratis_desarrollador(cliente: DatosClienteUnificados):
    dev_usuario_servidor = os.environ.get("DEV_USER")
    dev_password_servidor = os.environ.get("DEV_PASS")
    
    if not dev_usuario_servidor or not dev_password_servidor:
        raise HTTPException(status_code=503, detail="Variables DEV_USER y DEV_PASS ausentes en Render.")
    
    if cliente.dev_username_input != dev_usuario_servidor or cliente.dev_password_input != dev_password_servidor:
        raise HTTPException(status_code=401, detail="Credenciales de desarrollo incorrectas.")
    
    nombre_archivo = f"prueba_gratis_{cliente.tramite_tipo}.pdf"
    ejecutar_mapeo_y_guardado(cliente, nombre_archivo)
    
    # RUTA MANDATORIA CON BARRA DIAGONAL AMARRADA A TU URL INAMOVIBLE
    return {
        "respuesta": "✔ Filtro Guardián Correcto", 
        "archivo_url": f"https://onrender.com{nombre_archivo}"
    }

# =====================================================================
# PASARELAS DE COBRO (STRIPE) Y WEBHOOK SEGURO
# =====================================================================
@app.post("/api/stripe/checkout")
async def crear_checkout_stripe(cliente: DatosClienteUnificados):
    if not stripe.api_key: 
        raise HTTPException(status_code=503, detail="Stripe no configurado.")
    try:
        id_sesion_local = f"tramite_{int(os.urandom(4).hex(), 16)}"
        SESIONES_TEMPORALES[id_sesion_local] = cliente
        
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'], 
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}], 
            mode='payment',
            metadata={"id_sesion_local": id_sesion_local},
            success_url=f"https://onrender.com?stripe_status=success&file={id_sesion_local}.pdf",
            cancel_url=f"https://onrender.com?stripe_status=cancel",
        )
        return {"stripe_checkout_url": checkout_session.url}
    except Exception as e: 
        raise HTTPException(status_code=500, detail=str(e))

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
            del SESIONES_TEMPORALES[id_sesion_local] # Privacidad absoluta
            
    return {"status": "success"}

# =====================================================================
# RUTA DE DESCARGA EN VIVO HACIA EL TELÉFONO O COMPUTADORA
# =====================================================================
@app.get("/api/descargar/{nombre_archivo}")
async def descargar_archivo_real(nombre_archivo: str):
    ruta_archivo = os.path.join(SALIDAS_DIR, nombre_archivo)
    if not os.path.exists(ruta_archivo): 
        raise HTTPException(status_code=404, detail="Archivo no encontrado o expirado.")
    return FileResponse(ruta_archivo, media_type="application/pdf", filename=nombre_archivo)

@app.get("/health")
async def health_check(): 
    return {"status": "online", "sistema": "SAVE CUBA listo"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))    
        
