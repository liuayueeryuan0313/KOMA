"""Package a verified Docker archive and public templates as an offline release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile
import zipfile


def package(tag,architecture,image_tar,source_dir,output_dir):
    if not re.fullmatch(r'v\d+\.\d+\.\d+',tag):raise ValueError('Invalid release tag')
    if architecture not in ('amd64','arm64'):raise ValueError('Unsupported architecture')
    version=tag[1:];local_tag='koma:'+version+('-arm64' if architecture=='arm64' else '')
    image_tar=Path(image_tar);source_dir=Path(source_dir);output_dir=Path(output_dir)
    with tarfile.open(image_tar) as archive:
        manifest=json.load(archive.extractfile('manifest.json'))
        if len(manifest)!=1 or manifest[0]['RepoTags']!=[local_tag]:raise ValueError('Image tag mismatch')
        config=json.load(archive.extractfile(manifest[0]['Config']))
        if config.get('architecture')!=architecture or config.get('os')!='linux':raise ValueError('Image architecture mismatch')
        if config.get('config',{}).get('Labels',{}).get('org.opencontainers.image.version')!=version:raise ValueError('Image version mismatch')
    compose=(source_dir/'compose.yaml').read_text()
    compose,count=re.subn(r'^(\s*)image:.*$',lambda m:m[1]+'image: '+local_tag+'\n'+m[1]+'pull_policy: never',compose,flags=re.M)
    if count!=1:raise ValueError('Expected exactly one image in compose template')
    compose='\n'.join(line for line in compose.splitlines() if not line.lstrip().startswith('# build:'))+'\n'
    environment=(source_dir/'.env.example').read_text()
    tar_name=f'koma-{tag}-linux-{architecture}.tar'
    instructions=f'''课间 · KOMA {tag} / linux/{architecture}

1. 导入镜像：docker load -i {tar_name}
2. 复制 .env.example 为 .env，设置 PUBLIC_URL、PORT 和 BIND_ADDRESS。
3. 启动：docker compose up -d --wait
4. 读取首次管理员设置码：docker compose exec komama cat /data/setup-token

镜像标签：{local_tag}
包内 compose.yaml 使用 pull_policy: never，不会自动拉取其他镜像。
升级时保留原 Docker 数据卷及 master.key；不要执行 docker compose down -v。
本包不包含任何用户账号、密码、课表或数据库。
'''
    output_dir.mkdir(parents=True,exist_ok=True)
    bundle=output_dir/f'koma-docker-{tag}-linux-{architecture}.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        archive.write(image_tar,tar_name)
        archive.writestr('compose.yaml',compose)
        archive.writestr('.env.example',environment)
        archive.writestr('README.txt',instructions)
    checksum=hashlib.sha256()
    with bundle.open('rb') as file:
        for chunk in iter(lambda:file.read(1024*1024),b''):checksum.update(chunk)
    digest=Path(str(bundle)+'.sha256')
    digest.write_text(checksum.hexdigest()+'  '+bundle.name+'\n')
    return bundle,digest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for option in ['tag','architecture','image-tar','source-dir','output-dir']:parser.add_argument('--'+option,required=True)
    args=parser.parse_args()
    for path in package(args.tag,args.architecture,args.image_tar,args.source_dir,args.output_dir):print(path)
