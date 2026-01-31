import sqlite3
import pandas as pd
DB='PLN_Ultimate_Monitoring_V7.db'
conn=sqlite3.connect(DB)
try:
    df=pd.read_sql_query('SELECT id, tanggal, bulan, tahun, judul_pemberitaan, link_pemberitaan, pic_unit, akun, source, likes, views FROM monitoring_pln LIMIT 200', conn)
    print('ROWS:', len(df))
    print('\n-- id and link sample --')
    print(df[['id','link_pemberitaan']].head().to_string())
    print('\n-- full head --')
    print(df.head().to_string())
    print('\nDistinct bulan values:')
    print(sorted([str(x) for x in df['bulan'].dropna().unique().tolist()]))
    # pivot
    try:
        pivot = pd.pivot_table(df, index='pic_unit', columns='bulan', values='link_pemberitaan', aggfunc='count', fill_value=0)
        print('\nPivot shape:', pivot.shape)
        print(pivot.head().to_string())
    except Exception as e:
        print('pivot error', e)
    # top accounts
    try:
        top_acc = df.groupby(['akun','pic_unit']).agg({'link_pemberitaan':'count','likes': 'sum' if 'likes' in df.columns else 'size'}).rename(columns={'link_pemberitaan':'Post'})
        print('\nTop accounts by Post count:')
        print(top_acc.sort_values('Post', ascending=False).head(10).to_string())
    except Exception as e:
        print('top_acc error', e)
except Exception as e:
    print('Error reading DB:', e)
finally:
    conn.close()
