import os
import io
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

app = FastAPI()

# --- CONFIGURACIÓN DE RUTAS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLA_DIR = os.path.join(BASE_DIR, "plantilla")
SALIDAS_DIR = os.path.join(BASE_DIR, "salidas")

os.makedirs(SALIDAS_DIR, exist_ok=True)

# =====================================================================
# MOTOR DE IMPRESIÓN VISUAL POR COORDENADAS (CANVAS OVERLAY)
# =====================================================================
def rellenar_planilla_pdf(nombre_pdf_plantilla: str, datos_por_pagina: dict, id_archivo_salida: str):
    """
    Dibuja los textos directamente sobre las coordenadas de la página del PDF.
    datos_por_pagina estructura: { numero_pagina: [(texto, x, y, tamaño), ...] }
    """
    ruta_plantilla = os.path.join(PLANTILLA_DIR, nombre_pdf_plantilla)
    
    if not os.path.exists(ruta_plantilla):
        raise HTTPException(status_code=500, detail=f"No se encuentra la plantilla en 'plantilla/': {nombre_pdf_plantilla}")

    reader = PdfReader(ruta_plantilla)
    writer = PdfWriter()

    for index_pag, page in enumerate(reader.pages):
        num_pag_actual = index_pag + 1
        
        if num_pag_actual in datos_por_pagina:
            packet = io.BytesIO()
            can = canvas.Canvas(packet, pagesize=letter)
            can.setFont("Helvetica-Bold", 10)
            
            for texto, x, y, tamano in datos_por_pagina[num_pag_actual]:
                can.setFont("Helvetica-Bold", tamano)
                can.drawString(x, y, str(texto))
                
            can.save()
            packet.seek(0)
            
            overlay_reader = PdfReader(packet)
            page.merge_page(overlay_reader.pages[0])
            
        writer.add_page(page)

    ruta_salida = os.path.join(SALIDAS_DIR, id_archivo_salida)
    with open(ruta_salida, "wb") as f:
        writer.write(f)

# =====================================================================
# FUNCIONES AUXILIARES DE SANEAMIENTO Y TRADUCCIÓN
# =====================================================================
def corregir_y_sanear_texto(texto: str, es_obligatorio: bool = False, nombre_campo: str = "Campo"):
    if not texto and es_obligatorio:
        raise HTTPException(status_code=400, detail=f"El campo {nombre_campo} es obligatorio.")
    return str(texto).strip().upper() if texto else ""

def validar_y_limpiar_anumber(anumber: str, es_obligatorio: bool = False):
    if not anumber and es_obligatorio:
        raise HTTPException(status_code=400, detail="El A-Number es obligatorio.")
    return str(anumber).replace("-", "").replace(" ", "").strip()

def validar_y_limpiar_pasaporte(pasaporte: str, es_obligatorio: bool = False):
    if not pasaporte and es_obligatorio:
        raise HTTPException(status_code=400, detail="El número de pasaporte es obligatorio.")
    return str(pasaporte).strip()

def traducir_historial_laboral_ia(texto_espanol: str):
    if not texto_espanol:
        return "NONE"
    return texto_espanol.upper()
# =====================================================================
# MOTOR SEPARADOR Y EJECUTOR DE TRÁMITES (PRECISIÓN EXACTA)
# =====================================================================
def ejecutar_mapeo_y_guardado(cliente: 'DatosClienteUnificados', id_archivo_salida: str):
    nombre1 = corregir_y_sanear_texto(cliente.primer_nombre, es_obligatorio=True, nombre_campo="Primer Nombre")
    nombre2 = corregir_y_sanear_texto(cliente.segundo_nombre)
    apellido1 = corregir_y_sanear_texto(cliente.primer_apellido, es_obligatorio=True, nombre_campo="Primer Apellido")
    apellido2 = corregir_y_sanear_texto(cliente.segundo_apellido)
    
    if not cliente.fecha_nacimiento or "-" not in cliente.fecha_nacimiento:
        raise HTTPException(status_code=400, detail="¡Atención! La Fecha de Nacimiento es inválida o está vacía.")
    
    ano, mes, dia = cliente.fecha_nacimiento.split("-")
    
    # -----------------------------------------------------------------
    # FLUJO 1: RESIDENCIA Y TRABAJO USA (USCIS - G-1450, I-485, I-765)
    # -----------------------------------------------------------------
    if cliente.tramite_tipo == "paquete_completo_uscis":
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)

        # 1. G-1450 (Autorización de Tarjeta de Crédito - $1440)
        datos_g1450 = {
            1: [
                (apellido1, 72, 685, 10),
                (nombre1, 72, 635, 10),
                ("1440", 72, 410, 10)
            ]
        }
        rellenar_planilla_pdf("g1450.pdf", datos_g1450, "temp_g1450.pdf")

        # 2. I-485 (Solicitud de Residencia Permanente)
        datos_i485 = {
            1: [
                (apellido1, 72, 715, 10),
                (nombre1, 72, 675, 10),
                (anumber_limpio, 380, 715, 10),
                (mes, 72, 595, 10),
                (dia, 120, 595, 10),
                (ano, 160, 595, 10)
            ]
        }
        rellenar_planilla_pdf("i485.pdf", datos_i485, "temp_i485.pdf")

        # 3. I-765 (Permiso de Trabajo EAD)
        datos_i765 = {
            1: [
                (apellido1, 72, 725, 10),
                (nombre1, 72, 680, 10),
                (anumber_limpio, 380, 680, 10)
            ]
        }
        rellenar_planilla_pdf("i765.pdf", datos_i765, "temp_i765.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i485.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_i765.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)

    # -----------------------------------------------------------------
    # FLUJO 2: TRÁMITE CONSULAR (PASAPORTE CUBANO)
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "pasaporte_cubano":
        pasaporte_limpio = validar_y_limpiar_pasaporte(cliente.pasaporte_actual, es_obligatorio=True)
        provincia_limpia = corregir_y_sanear_texto(cliente.provincia_cuba, es_obligatorio=True, nombre_campo="Provincia de Origen")
        ano_salida_limpio = corregir_y_sanear_texto(cliente.ano_salida_cuba, es_obligatorio=True, nombre_campo="Año de Salida")
        empleo_espanol_limpio = corregir_y_sanear_texto(cliente.empleo_cuba_espanol, es_obligatorio=True, nombre_campo="Último empleo")

        campos_pasaporte = {
            1: [
                (nombre1, 72, 700, 10),
                (nombre2, 250, 700, 10),
                (apellido1, 72, 650, 10),
                (apellido2, 250, 650, 10),
                (dia, 72, 600, 10),
                (mes, 110, 600, 10),
                (ano, 150, 600, 10),
                (pasaporte_limpio, 72, 550, 10),
                (provincia_limpia, 72, 500, 10),
                (ano_salida_limpio, 72, 450, 10),
                (empleo_espanol_limpio, 72, 400, 10)
            ]
        }
        
        rellenar_planilla_pdf("pasaporte.pdf", campos_pasaporte, id_archivo_salida)

    # -----------------------------------------------------------------
    # FLUJO 3: CIUDADANÍA AMERICANA (N-400)
    # -----------------------------------------------------------------
    elif cliente.tramite_tipo == "naturalizacion_n400":
        anumber_limpio = validar_y_limpiar_anumber(cliente.anumber, es_obligatorio=True)
        
        # 1. G-1450 (Ciudadanía - $710)
        datos_g1450_n400 = {
            1: [
                (apellido1, 72, 685, 10),
                (nombre1, 72, 635, 10),
                ("710", 72, 410, 10)
            ]
        }
        rellenar_planilla_pdf("g1450.pdf", datos_g1450_n400, "temp_g1450.pdf")

        # 2. N-400 (Solicitud de Naturalización)
        datos_n400 = {
            1: [
                (apellido1, 72, 715, 10),
                (nombre1, 72, 675, 10),
                (anumber_limpio, 380, 715, 10)
            ]
        }
        rellenar_planilla_pdf("n400.pdf", datos_n400, "temp_n400.pdf")
        
        pdf_final = PdfWriter()
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_g1450.pdf"))
        pdf_final.append(os.path.join(SALIDAS_DIR, "temp_n400.pdf"))
        
        ruta_paquete = os.path.join(SALIDAS_DIR, id_archivo_salida)
        with open(ruta_paquete, "wb") as f:
            pdf_final.write(f)
            
    else:
        raise HTTPException(status_code=400, detail="El trámite comercial solicitado no existe en SAVE CUBA.")

# =====================================================================
# ESTRUCTURA DE DATOS Y ENDPOINT PRINCIPAL
# =====================================================================
class DatosClienteUnificados(BaseModel):
    primer_nombre: str
    segundo_nombre: str = ""
    primer_apellido: str
    segundo_apellido: str = ""
    fecha_nacimiento: str
    anumber: str = ""
    pasaporte_actual: str = ""
    provincia_cuba: str = ""
    ano_salida_cuba: str = ""
    empleo_cuba_espanol: str = ""
    tramite_tipo: str

@app.post("/procesar_tramite")
async def procesar_tramite(cliente: DatosClienteUnificados):
    id_archivo_final = f"tramite_{cliente.primer_apellido}_{cliente.primer_nombre}.pdf"
    
    try:
        ejecutar_mapeo_y_guardado(cliente, id_archivo_final)
        return {
            "estado": "éxito",
            "mensaje": "Documento generado correctamente por el sistema.",
            "archivo": id_archivo_final
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en la generación del PDF: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)    
