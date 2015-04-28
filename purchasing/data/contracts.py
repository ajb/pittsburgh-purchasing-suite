# -*- coding: utf-8 -*-

from purchasing.data.models import ContractBase, ContractProperty

def create_new_contract(contract_data):
    '''
    Creates a new contract and any associated properties
    from contract_data and returns the contract
    '''
    properties = contract_data.pop('properties', [])
    contract = ContractBase.create(**contract_data)
    for property in properties:
        _property = property.items()[0]
        ContractProperty.create(**{
            'contract_id': contract.id, 'key': _property[0], 'value': _property[1]
        })

    return contract

def update_contract(contract_id, contract_data):
    '''
    Updates an individual contract and returns the contract
    '''
    contract = get_one_contract(contract_id)
    contract.update(**contract_data)
    return contract

def update_contract_property(contract_property_id, property_data):
    '''
    Updates a contract property and returns the property
    '''
    property = ContractProperty.query.get(contract_property_id)
    _property_data = property_data.items()[0]
    property.update(**{
        'contract': property.contract, 'key': _property_data[0], 'value': _property_data[1]
    })

    return property

def delete_contract(contract_id):
    '''
    Deletes a contract and all associated properties
    '''
    contract = get_one_contract(contract_id)
    contract.delete()
    return True

def get_one_contract(contract_id):
    '''
    Returns a contract associated with a contract ID
    '''
    contract = ContractBase.query.get(contract_id)
    return contract

def get_all_contracts():
    '''
    Returns a list of contracts.
    TODO: Paginate these results.
    '''
    return ContractBase.query.all()