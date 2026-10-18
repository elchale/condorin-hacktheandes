from django.contrib import admin

from .models import Member, Ong, River


class MemberInline(admin.TabularInline):
    model = Member
    extra = 1
    fields = ['full_name', 'phone', 'role', 'position', 'is_legal_representative', 'email', 'dni', 'active']


@admin.register(Ong)
class OngAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_name', 'ruc', 'active', 'internal']
    list_filter = ['active', 'rivers']
    search_fields = ['name', 'short_name', 'ruc']
    filter_horizontal = ['rivers']
    inlines = [MemberInline]


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'ong', 'phone', 'role', 'position', 'active']
    list_filter = ['active', 'role', 'ong']
    search_fields = ['full_name', 'phone', 'dni']


@admin.register(River)
class RiverAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'region', 'protected_area']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ['name']}
    filter_horizontal = ['authorities']
