from studio.custom_block import (
    Block, CheckBox, DropDown, Label, SocketTypes, TextInput, add_block,
)

import cv2
import numpy
import json
import uuid
import urllib.parse
import urllib.request
import urllib.error

class PointCloud3D(Block):
    op_code = 'PointCloud3D'
    input_sockets = [
        SocketTypes.ImageAny('Image', multiple=False),
        SocketTypes.Boolean('Trigger', multiple=False),
        SocketTypes.Boolean('Reset', multiple=False)
    ]
    output_sockets = [
        SocketTypes.Generic('Point Cloud', multiple=False),
        SocketTypes.ImageRGB('Preview', multiple=False),
        SocketTypes.Integer('Points', multiple=False),
        SocketTypes.String('PLY Path', multiple=False),
        SocketTypes.String('Status', multiple=False)
    ]
    _augelab_generated_spec_version = 1
    _augelab_output_names = ('Point Cloud', 'Preview', 'Points', 'PLY Path', 'Status')

    def init(self):
        self.op_title = '3D Nokta Bulutu'
        self.width = 280
        self.height = 510
        self.tooltip = "Görüntüden 3D nokta bulutu (yerel GPU servisi). Canlı: kamerayı gezdirdikçe bulut büyür, Trigger .ply kaydeder. Tek görüntü: tek kareden 3D. Çok açı: 'Kare sayısı' kadar farklı kare toplayıp birleştirir; Klasör doluysa klasörü okur. Kart boyu > 0 ise sahnedeki ArUco kartıyla (DICT_4X4_50) bulut mm'ye ve kart eksenlerine ölçeklenir (Tek/Çok); 3D Ölçüm bloğu bunu ister. Reset temizler."
        self.param['label:mode'] = Label(text='Mod')
        self.param['mode'] = DropDown(name='mode', items=['Canlı', 'Tek görüntü', 'Çok açı'], selected_index=2, serializable=True)
        self.param['label:count'] = Label(text='Kare sayısı (Çok açı, 2-8)')
        self.param['count'] = TextInput(name='count', text='5')
        self.param['label:folder'] = Label(text='Klasör (Çok açı, doluysa Image yerine)')
        self.param['folder'] = TextInput(name='folder', text='')
        self.param['label:marker_mm'] = Label(text='Kart boyu (mm, 0 = ölçekleme yok)')
        self.param['marker_mm'] = TextInput(name='marker_mm', text='0')
        self.param['label:max_points'] = Label(text="Studio'ya aktarılan en fazla nokta")
        self.param['max_points'] = TextInput(name='max_points', text='200000')
        self.param['save_ply'] = CheckBox(name='save_ply', text='Sonuçları .ply kaydet (Tek/Çok)', init_state=False)
        self.param['label:server_url'] = Label(text='Servis adresi')
        self.param['server_url'] = TextInput(name='server_url', text='http://127.0.0.1:8770')
        self._augelab_generated_state = {}

    @staticmethod
    def _process(inputs, parameters, state, outputs):
        # tüm mod mantığı serviste (session.py); blok kareyi ve anahtar kenarlarını yollar
        url = str(parameters['server_url']).strip().rstrip('/')
        mode = {'Canlı': 'live', 'Tek görüntü': 'single'}.get(str(parameters['mode']), 'multi')
        sid = state.setdefault('sid', uuid.uuid4().hex)   # blok örneği başına servis oturumu
        img, trig, rst = inputs['Image'], inputs['Trigger'], inputs['Reset']
        trig_edge = trig is not None and bool(trig) and not state.get('trig_prev')
        rst_edge = bool(rst) and not state.get('rst_prev')
        state['trig_prev'], state['rst_prev'] = bool(trig), bool(rst)

        def get(path, timeout=5.0):
            with urllib.request.urlopen(url + path + '&sid=' + sid, timeout=timeout) as r:
                return r.read()

        try:
            body = b''
            if img is not None:
                f = numpy.asarray(img).astype(numpy.uint8)
                if f.ndim == 2:
                    f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
                elif f.shape[2] == 4:
                    f = cv2.cvtColor(f, cv2.COLOR_BGRA2BGR)
                w = 640 if mode == 'live' else 1280
                if f.shape[1] > w:
                    f = cv2.resize(f, (w, int(f.shape[0] * w / f.shape[1])), interpolation=cv2.INTER_AREA)
                body = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 85 if mode == 'live' else 92])[1].tobytes()
            q = urllib.parse.urlencode({'sid': sid, 'mode': mode, 'tc': int(trig is not None), 'trig': int(trig_edge), 'reset': int(rst_edge), 'count': int(parameters['count']), 'folder': str(parameters['folder']).strip().strip('"'), 'save': int(bool(parameters['save_ply'])), 'marker': float(parameters['marker_mm'])})
            req = urllib.request.Request(url + '/process?' + q, data=body, method='POST')
            with urllib.request.urlopen(req, timeout=1.0 if mode == 'live' else 120.0) as r:
                s = json.loads(r.read())
            if s['version'] != state.get('ver') or mode != state.get('mode'):
                # sonuç değişti: bulutu ve önizlemeyi bir kez çek
                rec = numpy.frombuffer(get('/result?max=' + str(max(int(parameters['max_points']), 1))), dtype=[('p', '<f4', 3), ('c', 'u1', 3)])
                state['cloud'] = {'points': rec['p'].copy(), 'colors': rec['c'].copy()} if len(rec) else None
                pv = get('/result_preview?x=1')
                state['preview'] = cv2.imdecode(numpy.frombuffer(pv, numpy.uint8), cv2.IMREAD_COLOR) if pv else None
                state['ver'], state['mode'] = s['version'], mode
            state['status'], state['points'] = s['status'], s['points']
            if s['ply']:
                state['ply'] = s['ply']
        except urllib.error.HTTPError as e:
            state['status'] = 'Servis hatası: ' + e.read().decode('utf-8', 'replace')[:160]
        except urllib.error.URLError:
            state['status'] = 'Servise ulaşılamadı: ' + url
        except Exception as e:
            state['status'] = 'Hata: ' + repr(e)[:160]

        outputs['Point Cloud'] = state.get('cloud')
        outputs['Preview'] = state.get('preview')
        outputs['Points'] = state.get('points', 0)
        outputs['PLY Path'] = state.get('ply', '')
        outputs['Status'] = state.get('status', 'Bekleniyor')

    def run(self):
        inputs = {
            'Image': self.input['Image'].data,
            'Trigger': self.input['Trigger'].data,
            'Reset': self.input['Reset'].data
        }
        parameters = {
            'mode': self.param['mode'].selected_item,
            'count': int(self.param['count'].value),
            'folder': str(self.param['folder'].value),
            'marker_mm': float(self.param['marker_mm'].value),
            'max_points': int(self.param['max_points'].value),
            'save_ply': bool(self.param['save_ply'].is_checked),
            'server_url': str(self.param['server_url'].value)
        }
        state = self._augelab_generated_state
        outputs = {
            'Point Cloud': None,
            'Preview': None,
            'Points': 0,
            'PLY Path': '',
            'Status': 'Bekleniyor'
        }
        if parameters['server_url'] not in ('',):
            self._process(inputs, parameters, state, outputs)
        unknown = set(outputs).difference(self._augelab_output_names)
        if unknown:
            raise ValueError(f"Undeclared generated outputs: {sorted(unknown)}")
        for output_name in self._augelab_output_names:
            self.output[output_name].data = outputs[output_name]


add_block(PointCloud3D.op_code, PointCloud3D)
