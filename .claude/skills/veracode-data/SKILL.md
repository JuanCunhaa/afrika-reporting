---
name: veracode-data
description: Planejar e construir adaptadores Veracode com equivalência a dashboards e sem invenção de métricas.
---
- Definir contrato por endpoint, autenticação, permissão, paginação, erro 429, timestamps, contexto e completude.
- Capturar proveniência sem tokens nem findings identificáveis.
- Nunca usar filtros de applications diretamente em users/scans/SCA por suposição.
- `first_found_date`, `created_date`, scan date e fechamento são semânticas diferentes.
- Contexto sandbox exige identidade/dedup definidos; não somar contagens de APIs divergentes.
- Conformidade do dashboard vale mais que fórmula conjecturada; inconsistência de nossa consulta => investigação, não "correção" do dashboard.
- Homologar modo real separadamente do fixture replay.
