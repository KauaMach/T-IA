# Extração de Dados - Projeto T-IA

Este diretório contém os pipelines responsáveis pela coleta, extração e processamento inicial de dados para o projeto T-IA. Ele é dividido em duas frentes principais:

- **extracao-diarios**: Pipeline focado na extração estruturada de informações de diários oficiais utilizando modelos e OCR.
- **extracao-docentes**: Pipeline para coleta e processamento de dados referentes ao corpo docente.

---

## Pré-requisitos

- **Python 3.9+** (ou superior)
- `pip` (Gerenciador de pacotes do Python)

---

## Configuração do Ambiente Local

Recomenda-se isolar as dependências do projeto utilizando um ambiente virtual (venv).

1. **Acesse o diretório do módulo de dados:**
   ```bash
   cd extracao-de-dados
   ```

2. **Crie um ambiente virtual (opcional, mas recomendado):**
   ```bash
   python -m venv venv
   ```

3. **Ative o ambiente virtual:**
   - No Linux/macOS:
     ```bash
     source venv/bin/activate
     ```
   - No Windows:
     ```bash
     venv\Scripts\activate
     ```

4. **Instale as dependências requeridas:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Configurando Variáveis de Ambiente

O pipeline utiliza credenciais e chaves (ex: acesso a APIs como DeepSeek, configurações de banco, etc.) que não devem ser versionadas.

- No diretório `extracao-diarios/`, edite o arquivo **`.env`** com as chaves necessárias para a execução. Se o arquivo não existir ou for apenas um `.env.example`, crie um arquivo `.env` válido seguindo a estrutura esperada pelo módulo de configurações (`src/mfe/config/settings.py`).

---

## Como Executar

Os pipelines possuem seus respectivos pontos de entrada (`main_pipeline.py`). Certifique-se de que o ambiente virtual está ativado antes de rodar os comandos abaixo.

### 1. Executando o Pipeline de Diários

Este pipeline fará o download/ingestão, OCR, extração e pós-processamento de documentos oficiais.

```bash
# Entre na pasta do pipeline de diários
cd extracao-diarios

# Execute o script principal
python main_pipeline.py
```

### 2. Executando o Pipeline de Docentes

Este pipeline fará a coleta e o mapeamento de informações relativas aos docentes.

```bash
# Retorne à pasta pai e entre no diretório de docentes
cd ../extracao-docentes

# Execute o script principal
python main_pipeline.py
```

---

## Estrutura Resumida dos Módulos

As duas pastas (`extracao-diarios` e `extracao-docentes`) compartilham uma arquitetura similar para facilitar a manutenção:

- `main_pipeline.py`: Ponto de entrada que orquestra todo o fluxo.
- `pipeline/`: Contém os passos lógicos sequenciais (ex: `docling`, `deepseek`, pós-processamento e processamento paralelo).
- `src/`: A base de código reutilizável (`mfe`), que inclui:
  - `config/`: Configurações de sistema e logs.
  - `db/`: Conexões e sessões de banco de dados.
  - `extractors/`: Lógica de extração base (OCR, Parsing de Vídeo, etc.).
  - `converters/`: Conversão entre diferentes tipos de arquivo (ex: PDF para texto/markdown).
