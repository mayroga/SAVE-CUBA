from pypdf import PdfReader

def extraer_mapeo_real(pdf_path, txt_output):
    reader = PdfReader(pdf_path)
    fields = reader.get_fields()
    
    with open(txt_output, "w", encoding="utf-8") as f:
        f.write(f"=== CAMPOS DETECTADOS EN: {pdf_path} ===\n\n")
        if not fields:
            f.write("No se detectaron campos interactivos en este PDF.\n")
            return
            
        for name, field in fields.items():
            field_type = field.get('/FT', 'Desconocido')
            f.write(f"Nombre Técnico: '{name}' | Tipo: {field_type}\n")

# Ejecutar la extracción para tus 4 documentos reales
extraer_mapeo_real("plantillas/pasaporte.pdf", "campos_pasaporte.txt")
extraer_mapeo_real("plantillas/i485.pdf", "campos_i485.txt")
extraer_mapeo_real("plantillas/i765.pdf", "campos_i765.txt")
extraer_mapeo_real("plantillas/g1450.pdf", "campos_g1450.txt")

print("¡Hecho! Revisa los archivos .txt generados para ver los nombres exactos de los campos.")
