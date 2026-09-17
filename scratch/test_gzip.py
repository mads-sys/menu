import gzip
import os

files = ['index.html', 'style.css', 'script.js', 'grid_view.js', 'grid_view.css']
tot_orig = 0
tot_gz = 0

print("--- GZIP REDUCTION TEST ---")
for f in files:
    if os.path.exists(f):
        data = open(f, 'rb').read()
        gz = gzip.compress(data, compresslevel=6)
        tot_orig += len(data)
        tot_gz += len(gz)
        pct = (1.0 - len(gz)/len(data)) * 100.0
        print(f"{f:<15}: {len(data)/1024:7.1f} KB -> {len(gz)/1024:6.1f} KB ({pct:.1f}% reduction)")

total_pct = (1.0 - tot_gz/tot_orig) * 100.0
print("-" * 50)
print(f"{'TOTAL':<15}: {tot_orig/1024:7.1f} KB -> {tot_gz/1024:6.1f} KB ({total_pct:.1f}% reduction)")
