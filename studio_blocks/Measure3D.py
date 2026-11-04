from studio.custom_block import (
    Block, CheckBox, DropDown, Label, SocketTypes, TextInput, add_block,
)

import cv2
import numpy
import json
import base64
import urllib.parse
import urllib.request
import urllib.error

class Measure3D(Block):
    op_code = 'Measure3D'
    input_sockets = [
        SocketTypes.Generic('Point Cloud', multiple=False)
    ]
    output_sockets = [
        SocketTypes.ImageRGB('View', multiple=False),
        SocketTypes.String('Measurements', multiple=False),
        SocketTypes.Generic('Objects', multiple=False),
        SocketTypes.Integer('Count', multiple=False),
        SocketTypes.String('Status', multiple=False)
    ]
    _augelab_generated_spec_version = 1
    _augelab_output_names = ('View', 'Measurements', 'Objects', 'Count', 'Status')

    def init(self):
        self.op_title = '3D Ölçüm'
        self.width = 280
        self.height = 270
        self.tooltip = "Kartla mm'ye ölçeklenmiş nokta bulutunda (3D Nokta Bulutu, Kart boyu > 0) masa üstündeki nesneleri ayırır ve her biri için boy x en x yükseklik verir. Kargo modunda etiketler cm ve desi (cm³/3000). View: üstten yükseklik haritası + kutular + etiketler. Objects: [{id, L, W, H (mm), desi, x, y, area_mm2}]. Bulut değişmedikçe yeniden ölçmez."
        self.param['cargo'] = CheckBox(name='cargo', text='Kargo modu (cm + desi)', init_state=False)
        self.param['label:min_height'] = Label(text='Masadan en az yükseklik (mm)')
        self.param['min_height'] = TextInput(name='min_height', text='8')
        self.param['label:server_url'] = Label(text='Servis adresi')
        self.param['server_url'] = TextInput(name='server_url', text='http://127.0.0.1:8770')
        self._augelab_generated_state = {}

    @staticmethod
    def _process(inputs, parameters, state, outputs):
        url = str(parameters['server_url']).strip().rstrip('/')
        cloud = inputs['Point Cloud']
        src = cloud.get('points') if isinstance(cloud, dict) else None
        cargo = bool(parameters['cargo'])
        key = (id(src), float(parameters['min_height']), cargo)
        if src is None:
            state['status'] = 'Nokta bulutu bekleniyor'
        elif key != state.get('key'):
            # ölçüm serviste (measure.py); yalnızca bulut ya da ayar değişince
            state['key'] = key
            try:
                pts = numpy.asarray(src, numpy.float32).reshape(-1, 3)
                rec = numpy.empty(len(pts), dtype=[('p', '<f4', 3), ('c', 'u1', 3)])
                rec['p'] = pts
                rec['c'] = numpy.asarray(cloud.get('colors'), numpy.uint8).reshape(-1, 3) if cloud.get('colors') is not None else 200
                q = urllib.parse.urlencode({'min_h': float(parameters['min_height']), 'cargo': int(cargo)})
                req = urllib.request.Request(url + '/measure?' + q, data=rec.tobytes(), method='POST')
                with urllib.request.urlopen(req, timeout=30.0) as r:
                    res = json.loads(r.read())
                objs = res['objects']
                state['objects'] = objs
                state['view'] = cv2.imdecode(numpy.frombuffer(base64.b64decode(res['image']), numpy.uint8), cv2.IMREAD_COLOR)
                if cargo:
                    rows = [str(o['id']) + ': ' + str(round(o['L'] / 10)) + ' x ' + str(round(o['W'] / 10)) + ' x ' + str(round(o['H'] / 10)) + ' cm · ' + str(o['desi']).replace('.', ',') + ' desi' for o in objs]
                else:
                    rows = [str(o['id']) + ': ' + str(round(o['L'])) + ' x ' + str(round(o['W'])) + ' x ' + str(round(o['H'])) + ' mm' for o in objs]
                state['table'] = '\n'.join(rows)
                state['status'] = str(len(objs)) + ' nesne ölçüldü' if objs else 'Masa üstünde nesne bulunamadı (bulut mm ölçekli mi?)'
            except urllib.error.URLError:
                state['status'] = 'Servise ulaşılamadı: ' + url
            except Exception as e:
                state['status'] = 'Hata: ' + repr(e)[:160]

        outputs['View'] = state.get('view')
        outputs['Measurements'] = state.get('table', '')
        outputs['Objects'] = state.get('objects')
        outputs['Count'] = len(state.get('objects') or [])
        outputs['Status'] = state.get('status', 'Bekleniyor')

    def run(self):
        inputs = {
            'Point Cloud': self.input['Point Cloud'].data
        }
        parameters = {
            'cargo': bool(self.param['cargo'].is_checked),
            'min_height': float(self.param['min_height'].value),
            'server_url': str(self.param['server_url'].value)
        }
        state = self._augelab_generated_state
        outputs = {
            'View': None,
            'Measurements': '',
            'Objects': None,
            'Count': 0,
            'Status': 'Bekleniyor'
        }
        if parameters['server_url'] not in ('',):
            self._process(inputs, parameters, state, outputs)
        unknown = set(outputs).difference(self._augelab_output_names)
        if unknown:
            raise ValueError(f"Undeclared generated outputs: {sorted(unknown)}")
        for output_name in self._augelab_output_names:
            self.output[output_name].data = outputs[output_name]


add_block(Measure3D.op_code, Measure3D)
