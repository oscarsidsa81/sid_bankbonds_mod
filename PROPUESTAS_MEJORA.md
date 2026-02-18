# Propuestas de mejora para `sid_bankbonds_mod`

> Nota: se mantiene **sin cambios** el hook `post_init_migrate_from_studio` de `hooks.py`, ya que en tu contexto está funcionando correctamente.

## 1) Prioridad alta (impacto funcional inmediato)

### 1.1 Unificar criterio de estados de pedidos (`sale` vs `done`)

Actualmente la lógica del módulo usa mayoritariamente pedidos confirmados en estado `sale` (cálculo de base y acciones), mientras que en una vista de `sale.quotations` aparece dominio/decoración orientado a `done`.

**Riesgo:** inconsistencias en lo que ve el usuario vs lo que calcula el sistema.

**Propuesta:**
- Decidir una regla única de negocio:
  - Opción A: considerar solo `sale`.
  - Opción B: considerar `sale` y `done`.
- Aplicar esa regla de forma consistente en:
  - computes de Python,
  - dominios XML,
  - texto funcional del README.

**Criterio de aceptación:** un mismo conjunto de pedidos produce el mismo resultado en smart buttons, listas y campos calculados.

---

### 1.2 Endurecer transición de estados de aval

El statusbar es clickable en formulario y eso puede permitir cambios manuales de estado fuera del flujo esperado.

**Propuesta:**
- Mantener transiciones guiadas por botones/métodos (`action_request`, `action_activate`, etc.).
- Añadir validación en `write` cuando cambie `state` para bloquear saltos no permitidos.

**Criterio de aceptación:** no se puede pasar de `draft` a `expired` (u otros saltos no válidos) sin usar la transición definida.

---

## 2) Prioridad media (mantenibilidad y claridad)

### 2.1 Eliminar duplicidad de decoradores y reglas

Hay redundancias en `@api.depends` y en validaciones de jerarquía parent/child.

**Propuesta:**
- Dejar un único `@api.depends` por método.
- Consolidar constraints repetidas de parent/child para evitar mensajes duplicados y ambigüedad.

**Criterio de aceptación:** mismo comportamiento funcional con menos código repetido y validaciones coherentes.

---

### 2.2 Documentar claramente el modelo de jerarquía de contratos

El módulo maneja principal/adenda y restricciones de cliente; conviene explicitar si se permite o no más de 2 niveles.

**Propuesta:**
- Documentar en README:
  - si se permite adenda de adenda,
  - cómo se valida cliente entre principal/adendas,
  - qué pasa si no hay pedidos confirmados.

**Criterio de aceptación:** usuario funcional entiende reglas sin leer Python.

---

## 3) Prioridad media-baja (rendimiento)

### 3.1 Optimizar computes con búsquedas por lote

Hay computes con búsquedas por registro (`search`/`search_count` dentro de loops), lo que puede penalizar en bases grandes.

**Propuesta:**
- Revisar `_compute_documento_origen` y contadores de compras para usar estrategias por lote (`read_group`, mapeos previos).

**Criterio de aceptación:** menos consultas SQL al abrir listas masivas y tiempos de respuesta más estables.

---

## 4) Calidad y pruebas (recomendado)

### 4.1 Añadir tests de regresión mínimos

**Paquete de tests propuesto (mínimo viable):**
- Cálculo `base_pedidos` según regla de estados elegida.
- Restricciones principal/adenda con cliente distinto.
- Transiciones de estado permitidas/no permitidas.
- Automatización de creación/actualización de documento PDF.

**Criterio de aceptación:** tests verdes en CI y detección temprana de regresiones.

---

## Roadmap sugerido por PRs (sin tocar hook)

1. **PR-1 (rápido):** consistencia `sale/done` + ajuste de vistas + README.
2. **PR-2 (seguridad funcional):** validación de transiciones de estado en `write`.
3. **PR-3 (higiene):** limpieza de redundancias en depends/constraints.
4. **PR-4 (performance):** optimización de computes por lote.
5. **PR-5 (tests):** suite mínima de regresión.

---

## Mi recomendación práctica

Si quieres impacto inmediato con bajo riesgo: ejecuta **PR-1 + PR-2** primero. 
Eso mejora coherencia de datos y evita errores operativos, sin tocar migración/hook.
