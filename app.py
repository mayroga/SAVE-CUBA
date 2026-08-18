import os
import re
import shutil
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from deep_translator import GoogleTranslator
from pypdf import PdfReader, PdfWriter
from openai import OpenAI
import google.generativeai as genai

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
client_openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

# Configuración de rutas del servidor
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLAS_DIR = os.path.join(BASE_DIR, "plantillas")
SALIDAS_DIR = os.path.join(BASE_DIR, "descargas")

# Crear directorios automáticamente si no existen
os.makedirs(SALIDAS_DIR, exist_ok=True)

class DatosClienteUnificados(BaseModel):
    tramite_tipo: str # "paquete_completo_uscis", "pasaporte_cubano", o "naturalizacion_n400"
    primer_nombre: str
    segundo_nombre: Optional[str] = ""
    primer_apellido: str
    segundo_apellido: Optional[str] = ""
    fecha_nacimiento: str # Formato AAAA-MM-DD
    anumber: Optional[str] = ""
    empleo_cuba_espanol: Optional[str] = ""
    pasaporte_actual: Optional[str] = ""
    provincia_cuba: Optional[str] = ""
    ano_salida_cuba: Optional[str] = ""
    tarjeta_numero: Optional[str] = ""
    tarjeta_exp: Optional[str] = ""
    tarjeta_cvv: Optional[str] = ""
    monto_pago: Optional[str] = ""

# =====================================================================
# MOTOR DE INTELIGENCIA ARTIFICIAL Y TRADUCCIÓN CON RESPALDO TRIPLE
# =====================================================================

def procesar_texto_con_ia_y_respaldo(texto_espanol: str) -> str:
    """
    1. Revisa la ortografía y redacción en español.
    2. Traduce a inglés técnico legal adecuado para formularios de USCIS.
    3. Usa OpenAI (Principal) -> Gemini (Respaldo) -> Traductor Básico Gratis (Seguridad).
    """
    if not texto_espanol or not texto_espanol.strip():
        return ""

    prompt_instruccion = f"""
    Actúa como un preparador de documentos de inmigración experto en Estados Unidos. 
    Primero, analiza el siguiente texto en español, corrige cualquier error de ortografía, redacción o coherencia. 
    Luego, tradúcelo a un inglés formal, técnico y legal adecuado para los formularios de USCIS (como el I-485 o I-765). 
    Devuelve ÚNICAMENTE la traducción final en inglés, en letras MAYÚSCULAS y sin textos aclaratorios.
    
    Texto a procesar: "{texto_espanol}"
    """

    # --- MOTOR 1: OpenAI (ChatGPT) ---
    if os.environ.get("OPENAI_API_KEY"):
        try:
            response = client_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt_instruccion}],
                temperature=0.3
            )
            return response.choices.message.content.strip().upper()
        except Exception as e:
            print(f"SAVE CUBA Alerta: Falló OpenAI, usando Gemini. Motivo: {e}")

    # --- MOTOR 2: Gemini (Google) ---
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
        raise HTTPException(status_code=500, detail=f"Error crítico en SAVE CUBA: Todos los motores de traducción fallaron. {str(e)}")

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

def rectificar_tarjeta(numero_tarjeta: Optional[str]) -> str:
    if not numero_tarjeta:
        return ""
    return re.sub(r'\D', '', numero_tarjeta.strip())

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
# =====================================================================
# RUTA CENTRAL DE PROCESAMIENTO
# =====================================================================
@app.post("/api/asistente")
async def procesar_automatizacion(cliente: DatosClienteUnificados):
    # Intentar leer la variable global dentro del ámbito para la respuesta URL
    api_url_base = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
    
    try:
        # 1. Saneamiento estricto de inputs mediante el motor de rectificación
        nombre1 = rectificar_texto_general(cliente.primer_nombre, es_obligatorio=True, nombre_campo="Primer Nombre")
        nombre2 = rectificar_texto_general(cliente.segundo_nombre)
        apellido1 = rectificar_texto_general(cliente.primer_apellido, es_obligatorio=True, nombre_campo="Primer Apellido")
        apellido2 = rectificar_texto_general(cliente.segundo_apellido)
        provincia = rectificar_texto_general(cliente.provincia_cuba)
        
        pasaporte_rectificado = rectificar_pasaporte(cliente.pasaporte_actual, es_obligatorio=(cliente.tramite_tipo == "pasaporte_cubano"))
        anumber_rectificado = rectificar_anumber(cliente.anumber, es_obligatorio=(cliente.tramite_tipo in ["paquete_completo_uscis", "naturalizacion_n400"]))
        
        tarjeta_limpia = rectificar_tarjeta(cliente.tarjeta_numero)

        if not cliente.fecha_nacimiento or "-" not in cliente.fecha_nacimiento:
            raise HTTPException(status_code=400, detail="Error en SAVE CUBA: La fecha de nacimiento es inválida o está vacía.")
        
        ano, mes, dia = cliente.fecha_nacimiento.split("-")
        fecha_formateada_usa = f"{mes}/{dia}/{ano}"

        # 2. Traducción Avanzada con Inteligencia Artificial (OpenAI -> Gemini -> Red de seguridad)
        empleo_ingles = ""
        if cliente.empleo_cuba_espanol and cliente.empleo_cuba_espanol.strip():
            # Corrige ortografía en español y traduce a inglés técnico oficial en mayúsculas
            empleo_ingles = procesar_texto_con_ia_y_respaldo(cliente.empleo_cuba_espanol)

        # =====================================================================
        # FLUJOS COMERCIALES DE IMPRESIÓN Y RELLENADO DE PLANILLAS
        # =====================================================================

        # CONDICIÓN 1: Paquete de Residencia USA Completo (Ley de Ajuste Cubano)
        if cliente.tramite_tipo == "paquete_completo_uscis":
            # Rellenar formulario de Residencia Permanente I-485
            campos_i485 = {
                "Given Name": nombre1,
                "Middle Name": nombre2,
                "Family Name": apellido1,
                "A-Number": anumber_rectificado,
                "Birth Date": fecha_formateada_usa,
                "Employment History": empleo_ingles
            }
            rellenar_planilla_pdf("plantilla_i485.pdf", campos_i485, "temp_i485.pdf")
            
            # Rellenar formulario de Autorización de Empleo I-765
            campos_i765 = {
                "First Name": nombre1,
                "Last Name": apellido1,
                "Alien Registration Number": anumber_rectificado
            }
            rellenar_planilla_pdf("plantilla_i765.pdf", campos_i765, "temp_i765.pdf")
            
            # Rellenar formulario de Pago con Tarjeta de Crédito G-1450
            campos_g1450 = {
                "Given Name": nombre1,
                "Family Name": apellido1,
                "Credit Card Number": tarjeta_limpia,
                "Expiration Date": cliente.tarjeta_exp,
                "CVV": cliente.tarjeta_cvv,
                "Amount": cliente.monto_pago
            }
            rellenar_planilla_pdf("plantilla_g1450.pdf", campos_g1450, "temp_g1450.pdf")
            
            # Unificar los tres archivos en un único archivo consolidado
            pdf_final = PdfWriter()
            pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf")) # El pago va primero arriba
            pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i485.pdf"))
            pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i765.pdf"))
            
            ruta_paquete = os.path.join(SALIDAS_DIR, "paquete_uscis_final.pdf")
            with open(ruta_paquete, "wb") as f:
                pdf_final.write(f)

            html_html = "✔ <strong>Paquete de Residencia Generado Exitosamente</strong><br>Campos inyectados, ortografía corregida y traducida correctamente en formato federal."
            return {"respuesta": html_html, "archivo_url": f"{api_url_base}/api/descargar/paquete_uscis_final.pdf"}

        # CONDICIÓN 2: Renovación o Prórroga de Pasaporte de Cuba
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
            rellenar_planilla_pdf("plantilla_pasaporte.pdf", campos_pasaporte, "pasaporte_cubano_final.pdf")
            
            html_html = "✔ <strong>Planilla Consular Completa</strong><br>Datos validados bajo el formato estricto de Inmigración de Cuba."
            return {"respuesta": html_html, "archivo_url": f"{api_url_base}/api/descargar/pasaporte_cubano_final.pdf"}

        # CONDICIÓN 3: Naturalización y Ciudadanía Americana N-400
        elif cliente.tramite_tipo == "naturalizacion_n400":
            campos_n400 = {
                "Given Name": nombre1,
                "Family Name": apellido1,
                "A-Number": anumber_rectificado,
                "Date of Birth": fecha_formateada_usa
            }
            rellenar_planilla_pdf("plantilla_n400.pdf", campos_n400, "temp_n400.pdf")
            
            campos_g1450 = {
                "Given Name": nombre1,
                "Family Name": apellido1,
                "Credit Card Number": tarjeta_limpia,
                "Expiration Date": cliente.tarjeta_exp,
                "CVV": cliente.tarjeta_cvv,
                "Amount": cliente.monto_pago
            }
            rellenar_planilla_pdf("plantilla_g1450.pdf", campos_g1450, "temp_g1450.pdf")
            
            pdf_final = PdfWriter()
            pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
            pdf_final.append(os.path.join(SALIDAS_DIR, "temp_n400.pdf"))
            
            ruta_paquete = os.path.join(SALIDAS_DIR, "paquete_ciudadania_final.pdf")
            with open(ruta_paquete, "wb") as f:
                pdf_final.write(f)

            html_html = "✔ <strong>Expediente de Ciudadanía Listo</strong><br>Formulario N-400 y hoja de pago G-1450 unificados correctamente."
            return {"respuesta": html_html, "archivo_url": f"{api_url_base}/api/descargar/paquete_ciudadania_final.pdf"}

        # Excepción si el frontend manda un tipo no mapeado
        raise HTTPException(status_code=400, detail="Trámite no reconocido.")
        
    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el motor central de SAVE CUBA: {str(e)}")

# =====================================================================
# RUTA DE DESCARGA EN VIVO (Manda el PDF real a la PC del cliente)
# =====================================================================
@app.get("/api/descargar/{nombre_archivo}")
async def descargar_archivo_real(nombre_archivo: str):
    ruta_archivo = os.path.join(SALIDAS_DIR, nombre_archivo)
    if not os.path.exists(ruta_archivo):
        raise HTTPException(status_code=404, detail="El archivo solicitado ya no está disponible en el servidor.")
    return FileResponse(ruta_archivo, media_type="application/pdf", filename=nombre_archivo)

# Configuración dinámica del puerto de Render para evitar bloqueos
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
