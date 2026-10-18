from django.contrib import admin

from .models import Admin, Member


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ['phone', 'created', 'last_sign_in_at']
    search_fields = ['phone']
    readonly_fields = ['consent_at', 'last_sign_in_at', 'created', 'updated']


@admin.register(Admin)
class AdminAdmin(admin.ModelAdmin):
    list_display = ['email', 'name', 'phone', 'active', 'created']
    list_editable = ['active']
