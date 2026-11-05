"""Generate the public knowledge manifest; never scans private runtime directories."""
from __future__ import annotations
from pathlib import Path


def main() -> None:
    root=Path(__file__).resolve().parents[1]
    names=[]
    for directory,suffix,minimum in (("commands",".md",621),("kb",".yaml",15),("skills",".yaml",6)):
        files=sorted((root/"data"/directory).glob("*"+suffix))
        assert len(files)==minimum,("public asset count changed; review before packaging",directory,len(files))
        names.extend(directory+"/"+path.name for path in files)
    target=root/"java-app/src/main/resources/knowledge/manifest.txt"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text("\n".join(names)+"\n",encoding="utf-8")
    print("Public knowledge manifest:",len(names),"files")


if __name__=="__main__":
    main()
