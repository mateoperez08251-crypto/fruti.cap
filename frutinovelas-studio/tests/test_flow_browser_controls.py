import re
from types import SimpleNamespace

import pytest

from frutinovelas.services.flow_browser_controls import (
    FlowBrowserSettings,
    FlowControlError,
    prepare_settings,
)


class Control:
    def __init__(self, page, name, group=None, attributes=None):
        self.page, self.name, self.group = page, name, group
        self.attributes = attributes or {}
    def count(self):
        return 1
    def is_visible(self):
        return True
    def is_enabled(self):
        return True
    def get_attribute(self, key):
        return self.attributes.get(key)
    def inner_text(self):
        return self.name
    def click(self):
        self.page.clicks.append(self.name)
        if self.group:
            for control in self.page.controls:
                if control.group == self.group:
                    control.attributes['aria-checked'] = 'false'
            self.attributes['aria-checked'] = 'true'
        if self.name == 'Agente':
            self.attributes['aria-pressed'] = 'false'


class Page:
    url = 'https://flow.google.com/project/test'
    def __init__(self, model='Nano Banana 2.1'):
        self.clicks, self.controls = [], []
        self.keyboard = SimpleNamespace(press=lambda key: None)
        for group, names in [('kind', ['Imagen','Video']), ('ratio',['16:9','9:16']), ('count',['x1','x2','x3','x4']),
                             ('resolution',['360p','720p']), ('duration',['4 s','6 s','8 s','10 s']), ('input',['Fotogramas','Ingredientes'])]:
            for name in names:
                self.controls.append(Control(self, name, group, {'aria-checked':'false'}))
        self.buttons = {name: Control(self,name) for name in ['Botón de configuración']}
        self.buttons['Seleccionar familia de modelos'] = Control(self, model+' arrow_drop_down')
        self.buttons['Agente'] = Control(self,'Agente', attributes={'aria-pressed':'true'})
    def locator(self, selector):
        return SimpleNamespace(count=lambda:0)
    def get_by_role(self, role, name, **kwargs):
        if role == 'button':
            return self.buttons[name]
        found = [control for control in self.controls if (name.search(control.name) if isinstance(name,re.Pattern) else name==control.name)]
        return found[0] if len(found)==1 else SimpleNamespace(count=lambda:len(found))
    def wait_for_timeout(self, value):
        pass


def test_explicit_image_settings_are_selected_and_verified_without_generating():
    page = Page()
    result = prepare_settings(page, FlowBrowserSettings(outputs=3))
    assert result['kind']=='image' and result['aspect_ratio']=='9:16' and result['outputs']==3
    assert result['verified'] and not result['submitted'] and not result['agent_enabled']
    assert {'Imagen','9:16','x3','Agente'} <= set(page.clicks)
    assert 'Iniciar generación' not in page.clicks


def test_video_settings_include_resolution_duration_and_input_mode():
    page = Page(model='Omni 1.1 Flash')
    result = prepare_settings(page, FlowBrowserSettings(kind='video', outputs=1, model='Omni 1.1 Flash',
        duration_seconds=6, resolution='720p', video_input='Fotogramas'))
    assert result['duration_seconds']==6 and result['resolution']=='720p'
    assert {'Video','Fotogramas','6 s','720p','x1','9:16'} <= set(page.clicks)


def test_missing_duration_is_not_rounded_or_silently_replaced():
    page = Page(model='Omni 1.1 Flash')
    with pytest.raises(FlowControlError,match='duración'):
        prepare_settings(page, FlowBrowserSettings(kind='video',model='Omni 1.1 Flash',duration_seconds=5,resolution='720p',video_input='Fotogramas'))
    assert not any(name in page.clicks for name in ('4 s','6 s','8 s','10 s','Iniciar generación'))


def test_wrong_model_stops_before_generation():
    with pytest.raises(FlowControlError,match='modelo visible'):
        prepare_settings(Page(model='Different model'),FlowBrowserSettings())


@pytest.mark.parametrize('options', [{'outputs':0},{'outputs':5},{'outputs':True},{'kind':'audio'},{'model':''},{'duration_seconds':8}, {'kind':'video'}])
def test_invalid_or_incomplete_settings_are_rejected(options):
    with pytest.raises(FlowControlError):
        FlowBrowserSettings(**options)


def test_controller_refuses_other_tabs_and_domains():
    page = Page()
    page.url = 'https://accounts.google.com/'
    with pytest.raises(FlowControlError,match='pestaña'):
        prepare_settings(page,FlowBrowserSettings())
    assert not page.clicks
