================================
SID Bank Bonds – Sales Integration
================================

Descripción
===========

El módulo **sid_bankbonds_mod** introduce la gestión de *avales bancarios* dentro de Odoo 15 Enterprise y su integración directa con los procesos comerciales de ventas.

Un **aval** se modela como una entidad propia (`sid_bonds_orders`) que puede agrupar uno o varios contratos comerciales (*sale.quotations*), los cuales a su vez pueden estar relacionados con uno o varios pedidos de venta (*sale.order*).

El módulo permite:

- Asociar avales a contratos de venta.
- Calcular automáticamente la **base imponible de pedidos** vinculados a un aval.
- Visualizar y navegar desde el aval a los pedidos de venta relacionados.
- Gestionar el documento PDF del aval y almacenarlo automáticamente en **Odoo Documents**.
- Controlar el ciclo de vida del aval mediante estados (borrador, solicitado, vigente, cancelado, etc.).

Este módulo está pensado para entornos empresariales donde los avales forman parte del control financiero y contractual de las operaciones comerciales.

---

Funcionalidad principal
=======================

Gestión de Avales
-----------------

El modelo principal `sid_bonds_orders` permite registrar:

- Cliente (partner).
- Banco emisor.
- Tipo de aval.
- Fechas de emisión y vencimiento.
- Importe del aval.
- Estado del aval.
- Documento PDF asociado.

Un aval puede agrupar **varios contratos de venta** (*sale.quotations*), que constituyen el dato de entrada funcional del módulo.

---

Integración con Ventas
----------------------

Relación jerárquica:

- **Aval (`sid_bonds_orders`)**
  - → **Contratos (`sale.quotations`)**
    - → **Pedidos (`sale.order`)**

A partir de los contratos asociados al aval, el módulo:

- Localiza todos los pedidos de venta relacionados.
- Calcula la **Base Imponible de Pedidos** como la suma del `amount_untaxed` de los pedidos confirmados.
- Permite abrir desde el aval un listado filtrado de pedidos de venta vinculados mediante un *smart button*.

---

Gestión documental (Odoo Documents)
-----------------------------------

Cuando se adjunta un PDF al campo **PDF Aval**:

- Se crea o actualiza automáticamente un documento en **Odoo Documents**.
- El documento queda vinculado al aval (`res_model = sid_bonds_orders`).
- El PDF se almacena en una carpeta específica configurada para avales.
- Si el PDF se reemplaza, el documento existente se actualiza en lugar de crear duplicados.

Esta lógica se implementa mediante una **acción automatizada** (`base.automation`) que se ejecuta al crear o modificar el aval.

---

Estados del Aval
================

El aval dispone de un flujo de estados que permite reflejar su situación administrativa y financiera:

- Borrador
- Solicitado
- Vigente
- Vencido
- Cancelado
- Pendiente Banco
- Enviado a cliente
- Recibido cliente
- Solicitud de devolución
- Recuperado
- Solicitud de cancelación

Las transiciones están controladas mediante acciones del modelo.

---

Instalación
===========

1. Copiar el módulo `sid_bankbonds_mod` en el directorio de addons.
2. Asegurar las dependencias indicadas en el `__manifest__.py`.
3. Actualizar la lista de aplicaciones.
4. Instalar el módulo desde Apps.

Es necesario disponer del módulo **Odoo Documents** para la gestión documental.

---

Configuración
=============

- Crear o verificar la carpeta de Documents destinada a los avales.
- Asignar los permisos adecuados al grupo de usuarios que gestionarán avales.
- Revisar la acción automatizada asociada a la creación/modificación del aval con PDF.

No se requieren parámetros técnicos adicionales.

---

Uso
===

1. Crear un nuevo aval desde el menú correspondiente.
2. Asociar uno o varios contratos (*sale.quotations*).
3. Definir cliente, banco, tipo e importe del aval.
4. Adjuntar el PDF del aval.
5. Validar el aval según el flujo de estados.
6. Consultar la base imponible de pedidos y acceder a los pedidos relacionados desde el propio aval.

---

Limitaciones conocidas
======================

- El módulo asume que los pedidos de venta están correctamente vinculados a contratos (*sale.quotations*).
- El cálculo de importes se basa en pedidos confirmados (`state = sale`).
- El nombre del archivo PDF se gestiona a nivel de Documents/Attachments.

---

Bug Tracker
===========

Las incidencias deben reportarse a través del repositorio del proyecto o al responsable de mantenimiento del módulo.

---

Créditos
========

Autor
-----

- SID – Desarrollo Odoo

Mantenimiento
-------------

- Equipo interno SID

---

Licencia
========

Este módulo se distribuye bajo licencia **LGPL-3** (o la que corresponda según política del proyecto).
