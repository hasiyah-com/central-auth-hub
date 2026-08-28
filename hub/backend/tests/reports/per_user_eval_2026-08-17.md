# รายงานประเมินโมเดลรายคน (Per-User RBA) — 2026-08-17

user                     test_n  atk   Prec  Recall     F1    ROC     PR
```
6660506018                  220   20  0.692   0.450  0.545  0.890  0.542
furafae                     109   20  1.000   0.100  0.182  0.985  0.938
hasiyahdama5                220   20  0.500   0.350  0.412  0.909  0.584
jkfurakook                   58   20  1.000   0.650  0.788  0.954  0.947
risk-demo                   220   20  0.800   0.400  0.533  0.902  0.664
searozxcv                   220   20  0.769   0.500  0.606  0.867  0.628
xssearo                     220   20  0.875   0.350  0.500  0.912  0.673
```

## รวมทุกคน
- ROC-AUC = 0.916 | PR-AUC = 0.676

## Detection แยกตามชนิด anomaly
- attack_ip            0/14
- burst_failed         43/70
- impossible_travel    6/14
- new_country          1/14
- new_device           2/14
- odd_hour             4/14
