# DC/CCN072 - TÓPICOS EM INTELIGÊNCIA ARTIFICIAL (2026.1)

Repositório organizado para a disciplina de Tópicos em IA da UFPI.

## 📂 Estrutura do Projeto

- **`data/`**: Centralização de dados coletados e processados.
  - `raw/`: Dados brutos (CSVs, PDFs de docentes, logs).
  - `processed/`: Relatórios e dados limpos.
- **`docs/`**: Materiais de apoio, apresentações e enunciados de atividades.
  - `arquitetura/`: PDFs sobre arquitetura de LLMs.
  - `coleta_dados/`: Materiais sobre webscraping e coleta.
  - `preparacao_dados/`: Materiais sobre limpeza e preparação.
- **`modules/`**: Código-fonte organizado por atividade.
  - `coleta_dados/`: Scripts de scraping e exercícios.
    - `webscraping_diario/`: Módulo principal de coleta do Diário Oficial.
  - `preparacao_dados/`: (Em breve) Scripts de limpeza e estruturação.

## 🚀 Como Executar o Webscraping

O módulo de webscraping do Diário Oficial foi configurado para salvar os dados automaticamente na pasta `data/raw/`.

### Requisitos
- Python 3.x
- Selenium
- WebDriver do Chrome (configurado no script)

### Execução
A partir da raiz do projeto:

```bash
# Para coletar os dados
python3 modules/coleta_dados/webscraping_diario/selenium_scraper.py

# Para gerar o relatório detalhado do Diário Oficial
python3 modules/coleta_dados/webscraping_diario/gerar_relatorio.py

# Para analisar arquivos dos docentes (tipos de arquivos, volumetria)
python3 modules/coleta_dados/docentes/analisar_docentes.py
```

Os resultados serão salvos em:
- CSV (Diário): `data/raw/diario_oficial/webscraping_diario.csv`
- CSV (Docentes): `data/raw/docentes/docentes_arquivos.csv`
- PDFs (Diário): `data/raw/diario_oficial/pdfs/`
- Relatório (Diário): `data/processed/relatorio_diario.md`
- Relatório (Docentes): `data/processed/relatorio_docentes.md`
