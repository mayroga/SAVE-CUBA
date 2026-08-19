import os
import re
import io
import unicodedata
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from deep_translator import GoogleTranslator
import google.generativeai as genai
from openai import OpenAI
from pypdf import PdfReader, PdfWriter

# Librerías de ReportLab para la inyección por coordenadas en tus PDFs planos
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI(title="SAVE CUBA - Motor Directo sin Fricciones")

# Permitir conexiones seguras con el index.html de tu URL fija
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLAS_DIR = os.path.join(BASE_DIR, "plantilla")
SALIDAS_DIR = os.path.join(BASE_DIR, "descargas")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(SALIDAS_DIR, exist_ok=True)

client_openai = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")) if os.environ.get("OPENAI_API_KEY") else None
if os.environ.get("GEMINI_API_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Esquema de datos limpio (Sin campos de usuario o contraseña)
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

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    ruta_html = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(ruta_html):
        raise HTTPException(status_code=404, detail="No se encontró index.html en static.")
    with open(ruta_html, "r", encoding="utf-8") as f:
        return f.read()

def corregir_y_sanear_texto(texto: Optional[str], es_obligatorio: bool = False, nombre_campo: str = "") -> str:
    if not texto or not texto.strip():
        if es_obligatorio:
            raise HTTPException(status_code=400, detail=f"El campo '{nombre_campo}' está vacío.")
        return ""
    texto_plano = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return " ".join(texto_plano.upper().strip().split())

def validar_y_limpiar_pasaporte(pasaporte_usuario: Optional[str], es_obligatorio: bool = False) -> str:
    if not pasaporte_usuario or not pasaporte_usuario.strip():
        if es_obligatorio: raise HTTPException(status_code=400, detail="Falta el número de Pasaporte Cubano.")
        return ""
    limpio = re.sub(r'[^A-Z0-9]', '', pasaporte_usuario.strip().upper())
    if len(limpio) != 7 or not re.match(r'^[A-Z]\d{6}$', limpio):
        raise HTTPException(status_code=400, detail="Estructura de Pasaporte Incorrecta (1 Letra y 6 Números, Ej: H123456).")
    return limpio

def validar_y_limpiar_anumber(anumber_usuario: Optional[str], es_obligatorio: bool = False) -> str:
    if not anumber_usuario or not anumber_usuario.strip():
        if es_obligatorio: raise HTTPException(status_code=400, detail="Falta el número de Extranjero (A-Number).")
        return ""
    limpio = re.sub(r'\D', '', anumber_usuario.strip())
    if len(limpio) != 9: raise HTTPException(status_code=400, detail="El A-Number exige exactamente 9 números enteros.")
    return limpio

def traducir_historial_laboral_ia(texto_espanol: str) -> str:
    if not texto_espanol or not texto_espanol.strip(): return ""
    prompt = f'Translate the following employment history to professional English for USCIS immigration forms. Return ONLY the translation in UPPERCASE:\n"{texto_espanol}"'
    if client_openai:
        try:
            response = client_openai.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], temperature=0.2)
            return response.choices.message.content.strip().upper()
        except Exception: pass
    try: return GoogleTranslator(source='es', target='en').translate(texto_espanol).upper()
    except Exception: return texto_espanol.upper()

def rellenar_planilla_pdf(nombre_plantilla: str, datos_mapeados: dict, nombre_salida: str) -> str:
    nombre_con_prefijo = nombre_plantilla if nombre_plantilla.startswith("plantilla_") else f"plantilla_{nombre_plantilla}"
    ruta_input = os.path.join(PLANTILLAS_DIR, nombre_con_prefijo)
    ruta_output = os.path.join(SALIDAS_DIR, nombre_salida)
    
    if not os.path.exists(ruta_input):
        raise HTTPException(status_code=500, detail=f"Falta archivo base plano: {nombre_con_prefijo}")
    
    try:
        packet = io.BytesIO()
        can = canvas.Canvas(packet, pagesize=letter)
        can.setFont("Helvetica-Bold", 10)
        can.setFillColorRGB(0, 0, 0)
        
        for campo, valor in datos_mapeados.items():
            if not valor: continue
            val_str = str(valor)
            
            if nombre_plantilla == "g1450.pdf":
                if "FamilyName" in campo: can.drawString(80, 595, val_str)
                elif "GivenName" in campo: can.drawString(260, 595, val_str)
                elif "MiddleName" in campo: can.drawString(440, 595, val_str)
                elif "Amount" in campo: can.drawString(450, 415, val_str)
            elif nombre_plantilla == "i485.pdf":
                if "Pt1Line3a_FamilyName" in campo: can.drawString(75, 688, val_str)
                elif "Pt1Line3b_GivenName" in campo: can.drawString(265, 688, val_str)
                elif "Pt1Line3c_MiddleName" in campo: can.drawString(440, 688, val_str)
                elif "AlienRegistrationNumber" in campo: can.drawString(435, 735, val_str)
                elif "Pt1Line8_DateOfBirth" in campo: can.drawString(440, 615, val_str)
                elif "Pt3Line1_RecentEmployer" in campo: can.drawString(75, 310, val_str)
            elif nombre_plantilla == "i765.pdf":
                if "Line1a_FamilyName" in campo: can.drawString(75, 712, val_str)
                elif "Line1b_GivenName" in campo: can.drawString(265, 712, val_str)
                elif "Line1c_MiddleName" in campo: can.drawString(440, 712, val_str)
                elif "AlienRegistrationNumber" in campo: can.drawString(435, 650, val_str)
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
                elif "CasillaNuevoPasaporte" in campo and val_str == "X": can.drawString(195, 742, "X")
                elif "CasillaPrimeraVez" in campo and val_str == "X": can.drawString(310, 742, "X")
            elif nombre_plantilla == "n400.pdf":
                if "P2_Line1_FamilyName" in campo: can.drawString(75, 630, val_str)
                elif "P2_Line1_GivenName" in campo: can.drawString(265, 630, val_str)
                elif "P2_Line1_MiddleName" in campo: can.drawString(440, 630, val_str)
                elif "Line1_AlienNumber" in campo: can.drawString(435, 715, val_str)
                elif "P2_Line8_DateOfBirth" in campo: can.drawString(75, 510, val_str)
        
        can.save()
        packet.seek(0)
        new_pdf = PdfReader(packet)
        existing_pdf = PdfReader(ruta_input)
        writer = PdfWriter()
        
        primera_pagina = existing_pdf.pages[0]
        primera_pagina.merge_page(new_pdf.pages[0])
        writer.add_page(primera_pagina)
        
        for i in range(1, len(existing_pdf.pages)):
            writer.add_page(existing_pdf.pages[i])
            
        with open(ruta_output, "wb") as f: writer.write(f)
        return ruta_output
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

# ENDPOINT DIRECTO DE PROCESAMIENTO INMEDIATO Y GRATUITO
@app.post("/api/asistente/procesar-directo")
async def procesar_tramite_directo(cliente: DatosClienteUnificados):
    nombre1 = corregir_y_sanear_texto(cliente.primer_nombre, es_obligatorio=True, nombre_campo="Primer Nombre")
    nombre2 = corregir_y_sanear_texto(cliente.segundo_nombre)
    apellido1 = corregir_y_sanear_texto(cliente.primer_apellido, es_obligatorio=True, nombre_campo="Primer Apellido")
    apellido2 = corregir_y_sanear_texto(cliente.segundo_apellido)
    
    if not cliente.fecha_nacimiento or "-" not in cliente.fecha_nacimiento:
        raise HTTPException(status_code=400, detail="La Fecha de Nacimiento es inválida.")
    ano, mes, dia = cliente.fecha_nacimiento.split("-")
    fecha_usa = f"{mes}/{dia}/{ano}"

    nombre_archivo_salida = f"save_cuba_{cliente.tramite_tipo}_{int(os.urandom(3).hex(), 16)}.pdf"

    if cliente.tramite_tipo == "paquete_completo_uscis":
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        empleo_ingles = traducir_historial_laboral_ia(cliente.empleo_cuba_espanol)
        rellenar_planilla_pdf("g1450.pdf", {"FamilyName": apellido1, "GivenName": nombre1, "MiddleName": nombre2, "Amount": "1440"}, "temp_g1450.pdf")
        rellenar_planilla_pdf("i485.pdf", {"Pt1Line3a_FamilyName": apellido1, "Pt1Line3b_GivenName": nombre1, "Pt1Line3c_MiddleName": nombre2, "AlienRegistrationNumber": anumber_limpio, "Pt1Line8_DateOfBirth": fecha_usa, "Pt3Line1_RecentEmployer": empleo_ingles}, "temp_i485.pdf")
        rellenar_planilla_pdf("i765.pdf", {"Line1a_FamilyName": apellido1, "Line1b_GivenName": nombre1, "Line1c_MiddleName": nombre2, "AlienRegistrationNumber": anumber_limpio}, "temp_i765.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i485.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i765.pdf"))
        with open(os.path.join(SALIDAS_DIR, id_archivo_salida), "wb") as f: 
            pdf_final.write(f)

    elif cliente.tramite_tipo in ["pasaporte_nuevo", "pasaporte_primera_vez"]:
        provincia_limpia = corregir_y_sanear_texto(cliente.provincia_cuba, es_obligatorio=True, nombre_campo="Provincia de Origen")
        ano_salida_limpio = corregir_y_sanear_texto(cliente.ano_salida_cuba, es_obligatorio=True, nombre_campo="Año de Salida")
        empleo_espanol = corregir_y_sanear_texto(cliente.empleo_cuba_espanol, es_obligatorio=True, nombre_campo="Último empleo")
        
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
            "OcupacionProfesion": empleo_espanol,
            "CasillaNuevoPasaporte": "X" if cliente.tramite_tipo == "pasaporte_nuevo" else "",
            "CasillaPrimeraVez": "X" if cliente.tramite_tipo == "pasaporte_primera_vez" else ""
        }
        rellenar_planilla_pdf("pasaporte.pdf", campos_pasaporte, id_archivo_salida)

    elif cliente.tramite_tipo == "naturalizacion_n400":
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        rellenar_planilla_pdf("n400.pdf", {"P2_Line1_FamilyName": apellido1, "P2_Line1_GivenName": nombre1, "P2_Line1_MiddleName": nombre2, "Line1_AlienNumber": anumber_limpio, "P2_Line8_DateOfBirth": fecha_usa}, "temp_n400.pdf")
        rellenar_planilla_pdf("g1450.pdf", {"FamilyName": apellido1, "GivenName": nombre1, "MiddleName": nombre2, "Amount": "710"}, "temp_g1450.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_n400.pdf"))
        with open(os.path.join(SALIDAS_DIR, id_archivo_salida), "wb") as f: 
            pdf_final.write(f)

    # Sustituir 'tudominio.com' por el dominio real configurado en el servidor
    return {"archivo_url": f"https://tudominio.com{id_archivo_salida}"}

@app.get("/api/descargar/{nombre_archivo}")
async def descargar_archivo_real(nombre_archivo: str):
    ruta_archivo = os.path.join(SALIDAS_DIR, nombre_archivo)
    if not os.path.exists(ruta_archivo): 
        raise HTTPException(status_code=404, detail="No encontrado.")
    return FileResponse(ruta_archivo, media_type="application/pdf", filename=nombre_archivo)

@app.get("/health")
async def health_check(): 
    return {"status": "online"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
        
