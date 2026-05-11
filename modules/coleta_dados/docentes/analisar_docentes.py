import os
import csv
from collections import Counter, defaultdict
from datetime import datetime

# Caminhos baseados na raiz do projeto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PATH_DOCENTES = os.path.join(BASE_DIR, "data/raw/docentes")
PATH_CSV_OUT = os.path.join(PATH_DOCENTES, "docentes_arquivos.csv")
PATH_RELATORIO_OUT = os.path.join(BASE_DIR, "data/processed/relatorio_docentes.md")

def analisar():
    if not os.path.exists(PATH_DOCENTES):
        print(f"[!] Pasta {PATH_DOCENTES} não encontrada.")
        return

    dados_arquivos = []
    
    # Percorre a estrutura: Docente / Ano / Mes / Dia / Arquivo
    for docente in os.listdir(PATH_DOCENTES):
        docente_path = os.path.join(PATH_DOCENTES, docente)
        if not os.path.isdir(docente_path): continue
        
        for ano in os.listdir(docente_path):
            ano_path = os.path.join(docente_path, ano)
            if not os.path.isdir(ano_path): continue
            
            for mes in os.listdir(ano_path):
                mes_path = os.path.join(ano_path, mes)
                if not os.path.isdir(mes_path): continue
                
                for dia in os.listdir(mes_path):
                    dia_path = os.path.join(mes_path, dia)
                    if not os.path.isdir(dia_path): continue
                    
                    for arquivo in os.listdir(dia_path):
                        full_path = os.path.join(dia_path, arquivo)
                        if os.path.isfile(full_path):
                            ext = os.path.splitext(arquivo)[1].lower() or "sem extensão"
                            
                            dados_arquivos.append({
                                "Docente": docente,
                                "Ano": ano,
                                "Mes": mes,
                                "Dia": dia,
                                "Arquivo": arquivo,
                                "Extensao": ext,
                                "Caminho": os.path.relpath(full_path, BASE_DIR)
                            })

    if not dados_arquivos:
        print("[!] Nenhum arquivo encontrado na pasta de docentes.")
        return

    # 1. Salva o CSV
    campos = ["Docente", "Ano", "Mes", "Dia", "Arquivo", "Extensao", "Caminho"]
    with open(PATH_CSV_OUT, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=campos, delimiter="|")
        writer.writeheader()
        writer.writerows(dados_arquivos)
    print(f"[*] CSV gerado: {PATH_CSV_OUT}")

    # 2. Gera o Relatório Markdown
    total_arquivos = len(dados_arquivos)
    stats_docente = Counter(d['Docente'] for d in dados_arquivos)
    stats_ext = Counter(d['Extensao'] for d in dados_arquivos)
    stats_ano = Counter(d['Ano'] for d in dados_arquivos)
    
    # Agrupamento por Docente e Extensão
    docente_ext = defaultdict(Counter)
    for d in dados_arquivos:
        docente_ext[d['Docente']][d['Extensao']] += 1

    relatorio = [
        "# 📑 Relatório de Arquivos de Docentes",
        f"\n> **Total de Arquivos:** {total_arquivos}",
        f"> **Data da Análise:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        "\n## 👤 Resumo por Docente",
        "| Docente | Total de Arquivos | % |",
        "| :--- | :---: | :---: |"
    ]

    for doc, count in sorted(stats_docente.items()):
        pct = (count / total_arquivos) * 100
        relatorio.append(f"| {doc} | {count} | {pct:.1f}% |")

    relatorio.extend([
        "\n## 📂 Distribuição por Tipo de Arquivo (Extensão)",
        "| Extensão | Quantidade | % |",
        "| :--- | :---: | :---: |"
    ])
    
    for ext, count in stats_ext.most_common():
        pct = (count / total_arquivos) * 100
        relatorio.append(f"| `{ext}` | {count} | {pct:.1f}% |")

    relatorio.append("\n## 📊 Detalhamento por Docente e Formato")
    for doc in sorted(docente_ext.keys()):
        relatorio.append(f"\n### {doc}")
        relatorio.append("| Extensão | Quantidade |")
        relatorio.append("| :--- | :---: |")
        for ext, count in sorted(docente_ext[doc].items()):
            relatorio.append(f"| `{ext}` | {count} |")

    relatorio.extend([
        "\n## 📅 Evolução Temporal (Arquivos por Ano)",
        "| Ano | Total |",
        "| :--- | :---: |"
    ])
    for ano in sorted(stats_ano.keys()):
        relatorio.append(f"| {ano} | {stats_ano[ano]} |")

    relatorio.append(f"\n\n---\n*Relatório gerado automaticamente em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}*")

    with open(PATH_RELATORIO_OUT, 'w', encoding='utf-8') as f:
        f.write("\n".join(relatorio))
    
    print(f"[*] Relatório gerado: {PATH_RELATORIO_OUT}")

if __name__ == "__main__":
    analisar()
