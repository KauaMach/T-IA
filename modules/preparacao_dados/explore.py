import pandas as pd
import os

def explore_data(parquet_path):
    """Explora os dados consolidados no arquivo Parquet."""
    if not os.path.exists(parquet_path):
        print(f"Arquivo {parquet_path} não encontrado.")
        return

    df = pd.read_parquet(parquet_path)
    
    print("\n" + "="*40)
    print(" EXPLORAÇÃO DE DADOS (PARQUET) ")
    print("="*40)
    
    print(f"\n[+] Total de Registros: {len(df)}")
    
    print("\n[+] Distribuição por Formato:")
    print(df['format'].value_counts())
    
    print("\n[+] Top 5 Arquivos (Maior Conteúdo):")
    if not df.empty:
        # Garante que char_count é numérico
        df['char_count'] = pd.to_numeric(df['char_count'], errors='coerce')
        print(df.nlargest(5, 'char_count')[['filename', 'format', 'char_count']])
    
    # Busca por termos
    term = 'UFPI'
    matches = df[df['text_content'].str.contains(term, case=False, na=False)]
    print(f"\n[+] Busca por '{term}': {len(matches)} ocorrências.")
    if not matches.empty:
        print(matches[['filename', 'char_count']].head())

if __name__ == "__main__":
    path = "data/processed/dataset_consolidado.parquet"
    explore_data(path)
