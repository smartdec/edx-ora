import json
import random
from lxml import etree

from xmodule.x_module import XModule
from xmodule.raw_module import RawDescriptor
from xmodule.xml_module import XmlDescriptor
from xmodule.exceptions import InvalidDefinitionError

DEFAULT = "_DEFAULT_GROUP"


def group_from_value(groups, v):
    ''' Given group: (('a',0.3),('b',0.4),('c',0.3)) And random value
    in [0,1], return the associated group (in the above case, return
    'a' if v<0.3, 'b' if 0.3<=v<0.7, and 'c' if v>0.7
'''
    sum = 0
    for (g, p) in groups:
        sum = sum + p
        if sum > v:
            return g

    # Round off errors might cause us to run to the end of the list
    # If the do, return the last element
    return g


class ABTestModule(XModule):
    """
    Implements an A/B test with an aribtrary number of competing groups

    Format:
    <abtest>
        <group name="a" portion=".1"><contenta/></group>
        <group name="b" portion=".2"><contentb/></group>
        <default><contentdefault/></default>
    </abtest>
    """

    def __init__(self, system, location, definition, instance_state=None, shared_state=None, **kwargs):
        XModule.__init__(self, system, location, definition, instance_state, shared_state, **kwargs)

        if shared_state is None:

            self.group = group_from_value(
                self.definition['data']['group_portions'].items(),
                random.uniform(0, 1)
            )
        else:
            shared_state = json.loads(shared_state)
            self.group = shared_state['group']

    def get_shared_state(self):
        return json.dumps({'group': self.group})

    def displayable_items(self):
        return [self.system.get_module(child)
                for child
                in self.definition['data']['group_content'][self.group]]


class ABTestDescriptor(RawDescriptor, XmlDescriptor):
    module_class = ABTestModule

    def __init__(self, system, definition=None, **kwargs):
        kwargs['shared_state_key'] = definition['data']['experiment']
        RawDescriptor.__init__(self, system, definition, **kwargs)

    @classmethod
    def definition_from_xml(cls, xml_object, system):
        experiment = xml_object.get('experiment')

        if experiment is None:
            raise InvalidDefinitionError("ABTests must specify an experiment. Not found in:\n{xml}".format(xml=etree.tostring(xml_object, pretty_print=True)))

        definition = {
            'data': {
                'experiment': experiment,
                'group_portions': {},
                'group_content': {DEFAULT: []},
            },
            'children': []}
        for group in xml_object:
            if group.tag == 'default':
                name = DEFAULT
            else:
                name = group.get('name')
                definition['data']['group_portions'][name] = float(group.get('portion', 0))

            child_content_urls = [
                system.process_xml(etree.tostring(child)).location.url()
                for child in group
            ]

            definition['data']['group_content'][name] = child_content_urls
            definition['children'].extend(child_content_urls)

        default_portion = 1 - sum(portion for (name, portion) in definition['data']['group_portions'].items())
        if default_portion < 0:
            raise InvalidDefinitionError("ABTest portions must add up to less than or equal to 1")

        definition['data']['group_portions'][DEFAULT] = default_portion
        definition['children'].sort()

        return definition

    def definition_to_xml(self, resource_fs):
        xml_object = etree.Element('abtest')
        xml_object.set('experiment', self.definition['data']['experiment'])
        for name, group in self.definition['data']['group_content'].items():
            if name == DEFAULT:
                group_elem = etree.SubElement(xml_object, 'default')
            else:
                group_elem = etree.SubElement(xml_object, 'group', attrib={
                    'portion': str(self.definition['data']['group_portions'][name]),
                    'name': name,
                })

            for child_loc in group:
                child = self.system.load_item(child_loc)
                group_elem.append(etree.fromstring(child.export_to_xml(resource_fs)))

        return xml_object