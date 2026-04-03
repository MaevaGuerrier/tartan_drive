# Compute Canada 

- `module load StdEnv/2023 python/3.10 gcc/12.3 opencv/4.10.0`
- `virtualenv --no-download tartan_venv` **ONLY DO THAT TO CREATE THE ENV ONCE**
- `source tartan_venv/bin/activate`
- `pip install --no-index --upgrade pip`
- `pip install --no-index -r requirements_computecan.txt`


# Needed packages are 
```
numpy
Pillow
opencv-python
tqdm
pyyaml
colorama
boto3
```

We also need **rosbag** installed though **bagpy** package see folder pkg_src for compute canada install of bagpy.