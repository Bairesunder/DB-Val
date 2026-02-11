# DBCheck — Validación y comparación de BBDD (drilling)

App en Streamlit para:
- Comparar OLD vs NEW (collar/survey/assay/litho) con tolerancia numérica
- Validar Collar / Survey / Assay
- Filtrar por **tipo de error** (TYPE) y descargar resultados (CSV/ZIP)

## Ejecutar en local
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy en Streamlit Community Cloud
- Sube estos archivos al repo
- New app → selecciona repo/branch → main file `app.py`
