"""Preserve independent FF states even when unused Q outputs share a net."""
from prove_tri_oracle_command_admission import AdmissionRoutes
class OldArrayRoutes(AdmissionRoutes):
    def state_leaf(self,context,instance):return f'ffstate.{context}.{instance}.IQ'
    def sequential(self,context,net,instance,master,pin,offset,width,connected,module):
        assert self.states.get(master)=={'ff':1},'Unsupported older-array sequential kind'
        assert width==1 and offset==0,'Nonscalar older-array sequential output'
        function=self.library[master,pin].get('function')
        assert function in ('IQ','IQN'),'Unsupported older-array state output function'
        leaf=self.state_leaf(context,instance);state=self.graph.variable(leaf)
        record=dict(context=context,instance=instance,master=master,pin_functions={p:self.library[master,p].get('function') for p in connected if self.library[master,p].get('direction')=='output'})
        assert self.sequential_cuts.setdefault(leaf,record)==record,'Older-array state identity changed'
        return state if function=='IQ' else self.graph.operation('!',state)
