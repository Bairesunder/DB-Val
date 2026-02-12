# Propuesta de mejoras para DBCheck

Este documento propone mejoras priorizadas para evolucionar la app en dos frentes:

1. **Funcionalidad (valor técnico y de negocio)**
2. **Interfaz visual / UX (claridad y velocidad de uso)**

---

## 1) Mejoras funcionales

## A. Prioridad alta (impacto inmediato)

### A1. Perfil de calidad automático por archivo
**Qué agregar**
- Un bloque inicial de "diagnóstico" por CSV antes de validar/comparar:
  - % de nulos por columna.
  - Conteo de duplicados por claves candidatas.
  - Distribución básica de rangos numéricos (min, p50, p95, max).

**Beneficio**
- Reduce errores de mapeo y acelera QA inicial.

### A2. Reglas configurables por proyecto
**Qué agregar**
- Permitir cargar un archivo de configuración (YAML/JSON) con:
  - Umbrales (p.ej. DLS, tolerancia numérica, máximos de leyes).
  - Nombres de columnas preferidas por cliente/proyecto.
  - Activación/desactivación de reglas.

**Beneficio**
- Evita reconfiguración manual y hace la app repetible/auditable.

### A3. Reporte consolidado en una sola salida
**Qué agregar**
- Un reporte único "run summary" que combine:
  - Inputs usados (archivos, encoding, parámetros).
  - Totales de errores por tipo y severidad.
  - Recomendaciones automáticas por error detectado.

**Beneficio**
- Facilita compartir resultados con equipos no técnicos.

### A4. Severidad y priorización de hallazgos
**Qué agregar**
- Clasificación de errores: `Crítico`, `Mayor`, `Menor`, `Info`.
- Orden de tablas por impacto.

**Beneficio**
- Permite decidir rápido qué corregir primero.

---

## B. Prioridad media (robustez y escalabilidad)

### B1. Historial de ejecuciones
**Qué agregar**
- Guardar metadatos de corrida (timestamp, parámetros, conteos).
- Comparar corrida actual vs corrida previa (tendencia de calidad).

**Beneficio**
- Mide mejora o degradación de calidad en el tiempo.

### B2. Soporte a más formatos
**Qué agregar**
- Adicional a CSV: Excel (`.xlsx`) y Parquet.
- Detección automática de separador/encoding cuando sea posible.

**Beneficio**
- Reduce fricción con fuentes heterogéneas.

### B3. Motor de reglas extensible
**Qué agregar**
- Arquitectura tipo "plugin" para nuevas validaciones:
  - Reglas por tabla (`collar/survey/assay/litho`).
  - Reglas cruzadas entre tablas (integridad referencial).

**Beneficio**
- Facilita incorporar checks específicos por operación minera.

### B4. Rendimiento para datasets grandes
**Qué agregar**
- Caché de lectura y transformaciones (`st.cache_data`).
- Procesamiento por chunks para archivos muy pesados.
- Indicadores de progreso durante validación.

**Beneficio**
- Mejor experiencia con archivos grandes y menor tiempo total.

---

## C. Prioridad baja (diferenciadores)

### C1. Asistente de mapeo inteligente
**Qué agregar**
- Recomendación de columnas con score de confianza + explicación.
- Opción de "aplicar mapeo recomendado" en un click.

### C2. Integración con base de datos
**Qué agregar**
- Conectores opcionales para leer/escribir desde DB corporativa.
- Export de errores a tabla de seguimiento.

### C3. Notificaciones y automatización
**Qué agregar**
- Alertas por email/Slack cuando los errores críticos superen umbral.
- Modo batch/CLI para pipelines programados.

---

## 2) Mejoras de interfaz visual (UX/UI)

## A. Flujo de uso

### A1. Wizard por pasos
**Qué mejorar**
- Reemplazar o complementar tabs con flujo guiado:
  1) Cargar archivo(s)
  2) Mapear columnas
  3) Configurar reglas
  4) Ejecutar
  5) Revisar y exportar

**Beneficio**
- Disminuye errores de configuración y mejora onboarding.

### A2. Estado visible de configuración
**Qué mejorar**
- Mostrar un panel "Checklist listo para ejecutar" con semáforos:
  - Archivos cargados
  - Mapeo completo
  - Parámetros válidos

### A3. Guardado de presets en UI
**Qué mejorar**
- Selector de "Preset" (por cliente/proyecto/campaña).

---

## B. Visualización de resultados

### B1. Dashboard ejecutivo al inicio de resultados
**Qué mejorar**
- KPIs compactos:
  - registros analizados,
  - errores totales,
  - % registros con error,
  - top 5 tipos de error.

### B2. Tablas con filtros avanzados
**Qué mejorar**
- Filtro por tipo de error, BHID, rango de profundidad y severidad.
- Búsqueda textual rápida y paginación.

### B3. Gráficos explicativos
**Qué mejorar**
- Barras: errores por tipo.
- Heatmap: columnas con mayor tasa de diferencia en comparaciones.
- Trendline: evolución entre corridas (si se implementa historial).

### B4. Navegación "error -> contexto"
**Qué mejorar**
- Al seleccionar un error, abrir vista detalle de filas vecinas del mismo pozo.

---

## C. Diseño visual

### C1. Sistema de color por severidad
- Rojo (`Crítico`), ámbar (`Mayor`), azul (`Menor`), gris (`Info`).

### C2. Tipografía y espaciado consistentes
- Mejorar jerarquía de títulos/subtítulos.
- Más aire entre bloques y botones de acción claros.

### C3. Empty states y ayudas contextuales
- Mensajes más instructivos cuando faltan archivos o mapeos.
- Tooltips en parámetros sensibles (DLS, tolerancia, máximos).

### C4. Modo oscuro / alto contraste
- Opción de accesibilidad para sesiones largas.

---

## 3) Roadmap sugerido (6 semanas)

### Sprint 1 (semanas 1-2)
- Perfil de calidad automático.
- Dashboard de resultados con severidad.
- Filtros avanzados básicos en tablas.

### Sprint 2 (semanas 3-4)
- Reglas configurables por YAML/JSON.
- Reporte consolidado descargable.
- Presets de configuración en UI.

### Sprint 3 (semanas 5-6)
- Historial de corridas y comparación temporal.
- Optimización de rendimiento (caché/chunks).
- Mejoras visuales de accesibilidad.

---

## 4) Métricas de éxito

- Tiempo medio de ejecución por dataset.
- Tiempo medio de configuración por usuario.
- % de corridas exitosas sin errores de mapeo.
- Reducción de errores críticos entre corridas.
- NPS interno de usuarios técnicos/geología/database.

---

## 5) Recomendación de implementación

Para maximizar valor con bajo riesgo:
1. **Primero**: severidad + dashboard + filtros (impacto directo en uso diario).
2. **Segundo**: reglas configurables y reporte consolidado (estandarización).
3. **Tercero**: historial y automatización (madurez operativa).
