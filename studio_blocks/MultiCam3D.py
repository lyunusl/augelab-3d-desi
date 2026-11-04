from studio.custom_block import (
    Block, CheckBox, DropDown, Label, SocketTypes, TextInput, add_block,
)

import cv2
import numpy
import json
import time
import uuid
import urllib.parse
import urllib.request
import urllib.error

class MultiCam3D(Block):
    op_code = 'MultiCam3D'
    input_sockets = [
        SocketTypes.ImageAny('Kamera 1', multiple=False),
        SocketTypes.ImageAny('Kamera 2', multiple=False),
        SocketTypes.ImageAny('Kamera 3', multiple=False),
        SocketTypes.Boolean('Trigger', multiple=False)
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
        self.op_title = 'Çok Kameralı 3D'
        self.width = 280
        self.height = 390
        self.tooltip = "2-3 sabit kameranın aynı andaki karelerini tek geçişte birleştirip 3D nokta bulutu çıkarır (yerel GPU servisi, Pi3X). Kart boyu > 0 ise sahnedeki ArUco kartıyla mm'ye ölçeklenir; 3D Ölçüm bloğuna bağlanır. Trigger bağlıysa yükselen kenarda çeker; değilse her 'Aralık' saniyede, görüntü değişmişse yeniden hesaplar."
        self.param['label:marker_mm'] = Label(text='Kart boyu (mm, 0 = ölçekleme yok)')
        self.param['marker_mm'] = TextInput(name='marker_mm', text='100')
        self.param['label:interval'] = Label(text='Aralık (sn, Trigger yoksa)')
        self.param['interval'] = TextInput(name='interval', text='2')
        self.param['label:max_points'] = Label(text="Studio'ya aktarılan en fazla nokta")
        self.param['max_points'] = TextInput(name='max_points', text='2000000')
        self.param['save_ply'] = CheckBox(name='save_ply', text='Sonuçları .ply kaydet', init_state=False)
        self.param['label:server_url'] = Label(text='Servis adresi')
        self.param['server_url'] = TextInput(name='server_url', text='http://127.0.0.1:8770')
        self._augelab_generated_state = {}

    @staticmethod
    def _process(inputs, parameters, state, outputs):
        url = str(parameters['server_url']).strip().rstrip('/')
        sid = state.setdefault('sid', uuid.uuid4().hex)   # blok örneği başına servis oturumu
        imgs = [inputs['Kamera ' + str(i)] for i in (1, 2, 3)]
        imgs = [im for im in imgs if im is not None]
        trig = inputs['Trigger']
        if isinstance(trig, str):
            # HMI kök girişi metin verir: her yeni değer (1, 2, 3...) bir ölçüm; boş/0 beklet
            key = trig.strip().casefold()
            trig_edge = key not in ('', '0', 'false') and key != state.get('trig_text')
            state['trig_text'] = key
        else:
            trig_edge = bool(trig) and not state.get('trig_prev')
            state['trig_prev'] = bool(trig)

        def prep(img):
            f = numpy.asarray(img).astype(numpy.uint8)
            if f.ndim == 2:
                f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
            elif f.shape[2] == 4:
                f = cv2.cvtColor(f, cv2.COLOR_BGRA2BGR)
            if f.shape[1] > 1280:
                f = cv2.resize(f, (1280, int(f.shape[0] * 1280 / f.shape[1])), interpolation=cv2.INTER_AREA)
            return f

        def get(path, timeout=10.0):
            with urllib.request.urlopen(url + path + '&sid=' + sid, timeout=timeout) as r:
                return r.read()

        run = False
        frames = None
        if len(imgs) < 2:
            state['status'] = 'En az 2 kamera bağla (' + str(len(imgs)) + ' var)'
        elif trig is not None:
            run = trig_edge
            if not run and state.get('cloud') is None:
                state['status'] = str(len(imgs)) + ' kamera hazır · Trigger bekleniyor'
        elif time.time() - state.get('check_t', 0.0) >= float(parameters['interval']):
            # Trigger yok: aralıkla bak, sahne değiştiyse (yeni koli vb.) yeniden hesapla
            state['check_t'] = time.time()
            frames = [prep(im) for im in imgs]
            sig = [cv2.cvtColor(cv2.resize(f, (32, 24), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(numpy.int16) for f in frames]
            prev = state.get('sig')
            run = prev is None or len(prev) != len(sig) or any(a.shape != b.shape or float(numpy.abs(a - b).mean()) > 3.0 for a, b in zip(prev, sig))
            if run:
                state['sig'] = sig

        if run:
            try:
                if frames is None:
                    frames = [prep(im) for im in imgs]
                bufs = [cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes() for f in frames]
                q = urllib.parse.urlencode({'sid': sid, 'marker': float(parameters['marker_mm']), 'save': int(bool(parameters['save_ply']))})
                req = urllib.request.Request(url + '/capture?' + q, data=b''.join(bufs), method='POST', headers={'X-Sizes': ','.join(str(len(b)) for b in bufs)})
                with urllib.request.urlopen(req, timeout=120.0) as r:
                    s = json.loads(r.read())
                rec = numpy.frombuffer(get('/result?max=' + str(max(int(parameters['max_points']), 1))), dtype=[('p', '<f4', 3), ('c', 'u1', 3)])
                state['cloud'] = {'points': rec['p'].copy(), 'colors': rec['c'].copy()} if len(rec) else None
                pv = get('/result_preview?x=1')
                state['preview'] = cv2.imdecode(numpy.frombuffer(pv, numpy.uint8), cv2.IMREAD_COLOR) if pv else None
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
            'Kamera 1': self.input['Kamera 1'].data,
            'Kamera 2': self.input['Kamera 2'].data,
            'Kamera 3': self.input['Kamera 3'].data,
            'Trigger': self.input['Trigger'].data
        }
        parameters = {
            'marker_mm': float(self.param['marker_mm'].value),
            'interval': float(self.param['interval'].value),
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


add_block(MultiCam3D.op_code, MultiCam3D)
