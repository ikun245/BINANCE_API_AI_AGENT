import PyInstaller.__main__
import os
import shutil

def build():
    # 确保输出目录干净
    if os.path.exists('dist'):
        shutil.rmtree('dist')
    if os.path.exists('build'):
        shutil.rmtree('build')

    params = [
        'main.py',
        '--name=BianlanceAI',
        '--onefile',
        '--windowed',
        '--clean',
        # 仅包含必要的代码文件夹，绝对不包含 config.json
        '--add-data=ui;ui', 
        '--collect-all=binance', # 确保 python-binance 的依赖被正确收集
        '--collect-all=pyqtgraph',
        '--hidden-import=PyQt5.sip',
        '--icon=NONE', 
    ]

    print("开始打包 BianlanceAI.exe (不包含本地 config.json)...")
    PyInstaller.__main__.run(params)
    print("\n打包完成！可执行文件位于 dist/BianlanceAI.exe")
    print("注意：运行 EXE 时，它会在同级目录下自动生成一个新的 config.json 供用户填写 API Key。")

if __name__ == "__main__":
    build()
