"""empty message

Revision ID: 22427b19886b
Revises: None
Create Date: 2015-04-23 13:49:29.783267

"""

# revision identifiers, used by Alembic.
revision = '22427b19886b'
down_revision = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('company',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_name', sa.String(length=255), nullable=False),
    sa.Column('contact_first_name', sa.String(length=255), nullable=True),
    sa.Column('contact_second_name', sa.String(length=255), nullable=True),
    sa.Column('contact_addr1', sa.String(length=255), nullable=True),
    sa.Column('contact_addr2', sa.String(length=255), nullable=True),
    sa.Column('contact_city', sa.String(length=255), nullable=True),
    sa.Column('contact_state', sa.String(length=255), nullable=True),
    sa.Column('contact_zip', sa.Integer(), nullable=True),
    sa.Column('contact_phone', sa.String(length=255), nullable=True),
    sa.Column('contact_email', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('flow',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('flow_name', sa.Text(), nullable=True),
    sa.Column('stage_order', postgresql.ARRAY(sa.Integer()), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('flow_name')
    )
    op.create_table('contract',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('contract_type', sa.String(length=255), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('current_stage_id', sa.Integer(), nullable=True),
    sa.Column('flow_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['current_stage_id'], ['stage.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['flow_id'], ['flow.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stage_property',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stage_id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=True),
    sa.Column('value', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['stage_id'], ['stage.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('company_contract_association',
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('contract_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['company.id'], ),
    sa.ForeignKeyConstraint(['contract_id'], ['contract.id'], )
    )
    op.create_table('contract_property',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('contract_id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=True),
    sa.Column('value', sa.String(length=255), nullable=True),
    sa.ForeignKeyConstraint(['contract_id'], ['contract.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('contract_property')
    op.drop_table('company_contract_association')
    op.drop_table('stage_property')
    op.drop_table('contract')
    op.drop_table('flow')
    op.drop_table('stage')
    op.drop_table('company')
    ### end Alembic commands ###